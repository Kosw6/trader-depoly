"""IAM-authenticated Lambda switch for two pinned SSM interface endpoints.

Never attached to the managed VPC: the switch must work with endpoints absent.
Configuration is deployed with the code, never accepted from the caller.
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

import boto3
from botocore.config import Config

OWNER = "trader-ssm-switch644"
CONFIRM_OFF = "DELETE_SSM_ENDPOINTS"
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
CLIENTS = {}


def client(session, name, sdk):
    # Reuse the large EC2/SSM service models across warm invocations.
    if name not in CLIENTS:
        CLIENTS[name] = session.client(name, config=sdk)
    return CLIENTS[name]


class Blocked(Exception):
    """An operation needing operator review, with a non-sensitive reason."""


def fingerprint(endpoint):
    policy = endpoint["PolicyDocument"]
    return {
        "VpcId": endpoint["VpcId"],
        "VpcEndpointType": endpoint["VpcEndpointType"],
        "ServiceName": endpoint["ServiceName"],
        "SubnetIds": sorted(endpoint["SubnetIds"]),
        "SecurityGroupIds": sorted(g["GroupId"] for g in endpoint["Groups"]),
        "PrivateDnsEnabled": endpoint["PrivateDnsEnabled"],
        "IpAddressType": endpoint["IpAddressType"],
        "DnsOptions": endpoint.get("DnsOptions", {}),
        "PolicyDocument": json.loads(policy) if isinstance(policy, str) else policy,
    }


def inspect(ec2, config):
    rows = []
    for page in ec2.get_paginator("describe_vpc_endpoints").paginate(
        Filters=[{"Name": "vpc-id", "Values": [config["vpcId"]]}]
    ):
        rows.extend(page["VpcEndpoints"])
    selected = {}
    # Check BOTH services before the first mutation, including partial pairs.
    for baseline in config["endpoints"]:
        service = baseline["ServiceName"]
        matches = [e for e in rows if e["ServiceName"] == service and e["State"] != "deleted"]
        if len(matches) > 1:
            raise Blocked("DUPLICATE_ENDPOINTS")
        if matches:
            endpoint = matches[0]
            tags = {t["Key"]: t["Value"] for t in endpoint.get("Tags", [])}
            if endpoint["VpcEndpointId"] != baseline["VpcEndpointId"] and tags.get("ManagedBy") != OWNER:
                raise Blocked("UNOWNED_ENDPOINT")
            if endpoint["State"] in ("available", "pending") and fingerprint(endpoint) != fingerprint(baseline):
                raise Blocked("ENDPOINT_CONFIGURATION_CHANGED")
            selected[service] = endpoint
    return selected


def idle_guard(ec2, ssm, config):
    instances = []
    for page in ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "vpc-id", "Values": [config["vpcId"]]}]
    ):
        instances.extend(i for r in page["Reservations"] for i in r["Instances"])
    if any(i["State"]["Name"] not in ("stopped", "terminated") for i in instances):
        raise Blocked("VPC_INSTANCES_NOT_ALL_STOPPED")
    ids = {i["InstanceId"] for i in instances}
    for page in ssm.get_paginator("describe_sessions").paginate(State="Active"):
        if any(s.get("Target") in ids for s in page["Sessions"]):
            raise Blocked("ACTIVE_SSM_SESSION")


def creation_args(baseline, request_id):
    spec = fingerprint(baseline)
    spec["PolicyDocument"] = json.dumps(spec["PolicyDocument"], separators=(",", ":"))
    tags = {t["Key"]: t["Value"] for t in baseline.get("Tags", []) if not t["Key"].startswith("aws:")}
    tags["ManagedBy"] = OWNER
    tags["ManagedVpc"] = baseline["VpcId"]
    return dict(
        spec,
        ClientToken=request_id + "-" + baseline["ServiceName"].split(".")[-1],
        TagSpecifications=[{"ResourceType": "vpc-endpoint", "Tags": [
            {"Key": k, "Value": v} for k, v in sorted(tags.items())
        ]}],
    )


def operate(event, config, ec2, ssm):
    if not isinstance(event, dict) or set(event) - {"action", "dryRun", "confirm"}:
        raise Blocked("INVALID_EVENT")
    action = event.get("action", "status")
    dry_run = event.get("dryRun", True)
    if action not in ("status", "on", "off") or not isinstance(dry_run, bool):
        raise Blocked("INVALID_ACTION_OR_DRY_RUN")
    current = inspect(ec2, config)
    result = {
        "action": action, "dryRun": dry_run,
        "endpoints": [{"service": k.split(".")[-1], "id": v["VpcEndpointId"], "state": v["State"]}
                      for k, v in sorted(current.items())],
        "ready": len(current) == 2 and all(v["State"] == "available" for v in current.values()),
        "off": not current,
    }
    if action == "status":
        return dict(result, status="OBSERVED")
    if any(e["State"] not in ("available", "pending") for e in current.values()):
        raise Blocked("TRANSITION_OR_FAILED_ENDPOINT_RECHECK_STATUS")
    if action == "off":
        if not dry_run and event.get("confirm") != CONFIRM_OFF:
            raise Blocked("OFF_CONFIRMATION_REQUIRED")
        idle_guard(ec2, ssm, config)
    if dry_run:
        return dict(result, status="PREVIEW_ONLY", planned=(
            [e["VpcEndpointId"] for e in current.values()] if action == "off" else
            [e["ServiceName"].split(".")[-1] for e in config["endpoints"] if e["ServiceName"] not in current]
        ))
    if action == "off":
        # Check state again immediately before deleting. Another operator starting
        # EC2 concurrently is outside this Lambda's lock; coordinate operationally.
        idle_guard(ec2, ssm, config)
        if not current:
            return dict(result, status="ALREADY_OFF")
        reply = ec2.delete_vpc_endpoints(VpcEndpointIds=sorted(e["VpcEndpointId"] for e in current.values()))
        if reply.get("Unsuccessful"):
            raise Blocked("DELETE_PARTIAL_OR_FAILED_RECHECK_STATUS")
        return dict(result, status="DELETE_REQUESTED", off=False, ready=False, recheckRequired=True)
    created = []
    request_id = str(uuid.uuid4())
    for baseline in config["endpoints"]:
        if baseline["ServiceName"] not in current:
            # No application-level retries or automatic rollback on partial pairs.
            response = ec2.create_vpc_endpoint(**creation_args(baseline, request_id))
            created.append(response["VpcEndpoint"]["VpcEndpointId"])
    return dict(result, status="CREATE_REQUESTED" if created else "ALREADY_PRESENT",
                createdIds=created, off=False, ready=result["ready"] and not created, recheckRequired=not result["ready"])


def lambda_handler(event, context):
    lock = None
    lock_token = str(uuid.uuid4())
    try:
        config = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
        sdk = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 1})
        session = boto3.Session(region_name=config["region"])
        # Lock only real on/off operations; read-only status/preview remains usable.
        if isinstance(event, dict) and event.get("action") in ("on", "off") and event.get("dryRun") is False:
            lock = client(session, "dynamodb", sdk)
            try:
                lock.put_item(TableName=os.environ["LOCK_TABLE"],
                    Item={"pk": {"S": "ssm-switch"}, "owner": {"S": lock_token}, "leaseUntil": {"N": str(int(time.time()) + 300)}},
                    ConditionExpression="attribute_not_exists(pk) OR leaseUntil < :now", ExpressionAttributeValues={":now": {"N": str(int(time.time()))}})
            except Exception as exc:
                lock = None
                if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    raise Blocked("ANOTHER_SWITCH_OPERATION_IN_PROGRESS") from None
                raise
        result = operate(event, config, client(session, "ec2", sdk), client(session, "ssm", sdk))
    except Blocked as exc:
        result = {"status": "BLOCKED", "reason": str(exc), "recheckRequired": True}
    except Exception as exc:
        # Do not log events, policies, credentials, SDK response bodies or traces.
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        result = {"status": "ERROR", "reason": code, "recheckRequired": True}
    finally:
        if lock is not None:
            try:
                lock.delete_item(TableName=os.environ["LOCK_TABLE"], Key={"pk": {"S": "ssm-switch"}},
                    ConditionExpression="#owner = :owner", ExpressionAttributeNames={"#owner": "owner"},
                    ExpressionAttributeValues={":owner": {"S": lock_token}})
            except Exception:
                # Preserve the lease on uncertain release; it expires after five
                # minutes, well beyond this Lambda's 90-second hard timeout.
                result["lockReleaseNeedsReview"] = True
    LOG.info("switch result=%s reason=%s", result["status"], result.get("reason", "-"))
    return result
