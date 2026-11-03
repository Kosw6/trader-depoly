import copy
import json
from unittest.mock import MagicMock

import pytest
from botocore.session import Session
from botocore.validate import validate_parameters
from botocore.exceptions import ClientError

import handler
from build import build
from handler import Blocked, CONFIRM_OFF, OWNER, creation_args, operate


@pytest.fixture
def setup():
    config = {"region": "ap-northeast-2", "accountId": "123456789012", "vpcId": "vpc-test", "endpoints": []}
    for n, service in enumerate(("ssm", "ssmmessages")):
        config["endpoints"].append({
            "VpcEndpointId": f"vpce-original{n}", "VpcId": "vpc-test", "VpcEndpointType": "Interface",
            "ServiceName": "com.amazonaws.ap-northeast-2." + service, "State": "available",
            "SubnetIds": ["subnet-test"], "Groups": [{"GroupId": "sg-test"}], "PrivateDnsEnabled": True,
            "IpAddressType": "ipv4", "DnsOptions": {"DnsRecordIpType": "ipv4"},
            "PolicyDocument": json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "*", "Resource": "*"}]}),
            "Tags": [{"Key": "Name", "Value": service}],
        })
    ec2, ssm = MagicMock(), MagicMock()
    def pages(name):
        paginator = MagicMock()
        paginator.paginate.return_value = ([{"VpcEndpoints": copy.deepcopy(config["endpoints"])}]
            if name == "describe_vpc_endpoints" else [{"Reservations": [{"Instances": [{"InstanceId": "i-test", "State": {"Name": "stopped"}}]}]}])
        return paginator
    ec2.get_paginator.side_effect = pages
    ssm.get_paginator.return_value.paginate.return_value = [{"Sessions": []}]
    ec2.delete_vpc_endpoints.return_value = {"Unsuccessful": []}
    ec2.create_vpc_endpoint.return_value = {"VpcEndpoint": {"VpcEndpointId": "vpce-created"}}
    return config, ec2, ssm


def set_endpoints(ec2, endpoints):
    original = ec2.get_paginator.side_effect
    def pages(name):
        if name != "describe_vpc_endpoints":
            return original(name)
        paginator = MagicMock()
        paginator.paginate.return_value = [{"VpcEndpoints": endpoints}]
        return paginator
    ec2.get_paginator.side_effect = pages


def test_status_never_mutates(setup):
    config, ec2, ssm = setup
    result = operate({}, config, ec2, ssm)
    assert result["ready"] and result["status"] == "OBSERVED"
    ec2.create_vpc_endpoint.assert_not_called()
    ec2.delete_vpc_endpoints.assert_not_called()


@pytest.mark.parametrize("event", [{"action": "off"}, {"action": "on"}])
def test_preview_is_default(setup, event):
    config, ec2, ssm = setup
    assert operate(event, config, ec2, ssm)["status"] == "PREVIEW_ONLY"
    ec2.create_vpc_endpoint.assert_not_called()
    ec2.delete_vpc_endpoints.assert_not_called()


@pytest.mark.parametrize("event", [[], {"action": "delete"}, {"action": "off", "dryRun": "false"}, {"action": "status", "vpcId": "other"}])
def test_caller_cannot_change_scope(setup, event):
    with pytest.raises(Blocked):
        operate(event, *setup)


def test_delete_needs_explicit_confirmation(setup):
    with pytest.raises(Blocked, match="OFF_CONFIRMATION_REQUIRED"):
        operate({"action": "off", "dryRun": False}, *setup)


def test_off_deletes_only_two_ids_and_requires_recheck(setup):
    config, ec2, ssm = setup
    result = operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)
    assert result["status"] == "DELETE_REQUESTED" and not result["off"]
    assert ec2.delete_vpc_endpoints.call_args.kwargs == {"VpcEndpointIds": ["vpce-original0", "vpce-original1"]}


@pytest.mark.parametrize("state", ["running", "pending", "stopping", "shutting-down", "unknown"])
def test_any_active_instance_blocks_off(setup, state):
    config, ec2, ssm = setup
    original = ec2.get_paginator.side_effect
    def pages(name):
        if name != "describe_instances":
            return original(name)
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Reservations": [{"Instances": [{"InstanceId": "i-test", "State": {"Name": state}}]}]}]
        return paginator
    ec2.get_paginator.side_effect = pages
    with pytest.raises(Blocked, match="NOT_ALL_STOPPED"):
        operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)
    ec2.delete_vpc_endpoints.assert_not_called()


def test_active_session_blocks_off(setup):
    config, ec2, ssm = setup
    ssm.get_paginator.return_value.paginate.return_value = [{"Sessions": []}, {"Sessions": [{"Target": "i-test"}]}]
    with pytest.raises(Blocked, match="ACTIVE_SSM_SESSION"):
        operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)
    ec2.delete_vpc_endpoints.assert_not_called()


@pytest.mark.parametrize("change", ["SecurityGroup", "Policy", "Subnet", "Dns"])
def test_config_drift_blocks_both_mutations(setup, change):
    config, ec2, ssm = setup
    endpoints = copy.deepcopy(config["endpoints"])
    if change == "SecurityGroup": endpoints[1]["Groups"] = [{"GroupId": "sg-other"}]
    if change == "Policy": endpoints[1]["PolicyDocument"] = '{"Statement":[]}'
    if change == "Subnet": endpoints[1]["SubnetIds"] = ["subnet-other"]
    if change == "Dns": endpoints[1]["PrivateDnsEnabled"] = False
    set_endpoints(ec2, endpoints)
    with pytest.raises(Blocked, match="CONFIGURATION_CHANGED"):
        operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)
    ec2.delete_vpc_endpoints.assert_not_called()


def test_on_does_not_duplicate_existing(setup):
    config, ec2, ssm = setup
    assert operate({"action": "on", "dryRun": False}, config, ec2, ssm)["status"] == "ALREADY_PRESENT"
    ec2.create_vpc_endpoint.assert_not_called()


def test_partial_pair_creates_only_missing_and_preserves_settings(setup):
    config, ec2, ssm = setup
    set_endpoints(ec2, config["endpoints"][:1])
    result = operate({"action": "on", "dryRun": False}, config, ec2, ssm)
    assert result["status"] == "CREATE_REQUESTED" and not result["ready"]
    assert ec2.create_vpc_endpoint.call_count == 1
    args = ec2.create_vpc_endpoint.call_args.kwargs
    assert args["ServiceName"].endswith("ssmmessages")
    assert args["SecurityGroupIds"] == ["sg-test"] and args["PrivateDnsEnabled"]
    assert json.loads(args["PolicyDocument"]) == json.loads(config["endpoints"][1]["PolicyDocument"])


@pytest.mark.parametrize("state", ["deleting", "failed", "rejected"])
def test_transitions_are_not_recreated_or_deleted(setup, state):
    config, ec2, ssm = setup
    endpoints = copy.deepcopy(config["endpoints"])
    endpoints[0]["State"] = state
    set_endpoints(ec2, endpoints)
    assert operate({"action": "status"}, config, ec2, ssm)["endpoints"][0]["state"] == state
    with pytest.raises(Blocked, match="TRANSITION"):
        operate({"action": "on", "dryRun": False}, config, ec2, ssm)
    ec2.create_vpc_endpoint.assert_not_called()


def test_owned_recreated_pair_is_recognized(setup):
    config, ec2, ssm = setup
    endpoints = copy.deepcopy(config["endpoints"])
    for n, endpoint in enumerate(endpoints):
        endpoint["VpcEndpointId"] = f"vpce-new{n}"
        endpoint["Tags"].append({"Key": "ManagedBy", "Value": OWNER})
    set_endpoints(ec2, endpoints)
    assert operate({"action": "status"}, config, ec2, ssm)["ready"]


def test_unowned_replacement_is_blocked(setup):
    config, ec2, ssm = setup
    endpoints = copy.deepcopy(config["endpoints"])
    endpoints[1]["VpcEndpointId"] = "vpce-unowned"
    set_endpoints(ec2, endpoints)
    with pytest.raises(Blocked, match="UNOWNED"):
        operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)


def test_delete_partial_failure_is_not_success(setup):
    config, ec2, ssm = setup
    ec2.delete_vpc_endpoints.return_value = {"Unsuccessful": [{"ResourceId": "vpce-original1"}]}
    with pytest.raises(Blocked, match="PARTIAL"):
        operate({"action": "off", "dryRun": False, "confirm": CONFIRM_OFF}, config, ec2, ssm)


def test_duplicate_service_blocks(setup):
    config, ec2, ssm = setup
    set_endpoints(ec2, config["endpoints"] + config["endpoints"][:1])
    with pytest.raises(Blocked, match="DUPLICATE"):
        operate({"action": "on", "dryRun": False}, config, ec2, ssm)


def test_sdk_shape_and_template_boundaries(setup):
    config, _, _ = setup
    model = Session().get_service_model("ec2")
    validate_parameters(creation_args(config["endpoints"][0], "request"), model.operation_model("CreateVpcEndpoint").input_shape)
    template = build(config)
    props = template["Resources"]["Switch"]["Properties"]
    assert "VpcConfig" not in props and "ReservedConcurrentExecutions" not in props
    assert {r["Type"] for r in template["Resources"].values()} == {"AWS::Lambda::Function", "AWS::IAM::Role", "AWS::Logs::LogGroup", "AWS::DynamoDB::Table"}
    compile(props["Code"]["ZipFile"], "index.py", "exec")
    policy = template["Resources"]["Role"]["Properties"]["Policies"][0]["PolicyDocument"]
    assert "StartInstances" not in json.dumps(policy) and "iam:PassRole" not in json.dumps(policy)


def runtime(setup, monkeypatch, tmp_path):
    config, ec2, ssm = setup
    monkeypatch.setattr(handler, "CLIENTS", {})
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(handler, "__file__", str(tmp_path / "handler.py"))
    monkeypatch.setenv("LOCK_TABLE", "test-lock")
    ddb, session = MagicMock(), MagicMock()
    session.client.side_effect = lambda name, **kw: {"ec2": ec2, "ssm": ssm, "dynamodb": ddb}[name]
    monkeypatch.setattr(handler.boto3, "Session", lambda **kw: session)
    return ec2, ddb


def test_concurrent_click_is_blocked_before_ec2(setup, monkeypatch, tmp_path):
    ec2, ddb = runtime(setup, monkeypatch, tmp_path)
    ddb.put_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
    result = handler.lambda_handler({"action": "on", "dryRun": False}, None)
    assert result["reason"] == "ANOTHER_SWITCH_OPERATION_IN_PROGRESS"
    ec2.get_paginator.assert_not_called()
    ddb.delete_item.assert_not_called()


def test_lock_is_owner_scoped_and_released_on_success(setup, monkeypatch, tmp_path):
    _, ddb = runtime(setup, monkeypatch, tmp_path)
    result = handler.lambda_handler({"action": "on", "dryRun": False}, None)
    assert result["status"] == "ALREADY_PRESENT"
    acquired = ddb.put_item.call_args.kwargs["Item"]
    released = ddb.delete_item.call_args.kwargs["ExpressionAttributeValues"][":owner"]
    assert acquired["owner"] == released


def test_lock_released_on_guard_failure(setup, monkeypatch, tmp_path):
    ec2, ddb = runtime(setup, monkeypatch, tmp_path)
    result = handler.lambda_handler({"action": "off", "dryRun": False}, None)
    assert result["reason"] == "OFF_CONFIRMATION_REQUIRED"
    ec2.delete_vpc_endpoints.assert_not_called()
    ddb.delete_item.assert_called_once()


def test_uncertain_lock_release_is_visible(setup, monkeypatch, tmp_path):
    _, ddb = runtime(setup, monkeypatch, tmp_path)
    ddb.delete_item.side_effect = RuntimeError("not printed")
    result = handler.lambda_handler({"action": "on", "dryRun": False}, None)
    assert result["status"] == "ALREADY_PRESENT" and result["lockReleaseNeedsReview"]
