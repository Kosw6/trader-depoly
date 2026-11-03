"""Build a deployable stack from a locally preserved, READ ONLY AWS baseline."""
import argparse
import json
from pathlib import Path

from handler import OWNER

HERE = Path(__file__).resolve().parent
NAME = "trader-ssm-endpoint-switch644"
LOCK_TABLE = "trader-ssm-switch644-lock"


def build(baseline):
    region, account = baseline["region"], baseline["accountId"]
    endpoints = baseline["endpoints"]
    assert region == "ap-northeast-2"
    assert len(endpoints) == 2 and {e["ServiceName"] for e in endpoints} == {
        "com.amazonaws.ap-northeast-2.ssm", "com.amazonaws.ap-northeast-2.ssmmessages"}
    assert len({e["VpcId"] for e in endpoints}) == 1
    assert all(e["VpcEndpointType"] == "Interface" and e["State"] == "available" and
               e["PrivateDnsEnabled"] and len(e["SubnetIds"]) == 1 and e["Groups"] for e in endpoints)
    config = dict(baseline, vpcId=endpoints[0]["VpcId"])
    arn = f"arn:aws:ec2:{region}:{account}:"
    endpoints_arn = arn + "vpc-endpoint/*"
    supporting = sorted({arn + "vpc/" + config["vpcId"]} |
                        {arn + "subnet/" + s for e in endpoints for s in e["SubnetIds"]} |
                        {arn + "security-group/" + g["GroupId"] for e in endpoints for g in e["Groups"]})
    statements = [
        {"Sid": "ObserveRegion", "Effect": "Allow", "Action": ["ec2:DescribeVpcEndpoints", "ec2:DescribeInstances", "ssm:DescribeSessions"],
         "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": region}}},
        {"Sid": "CreateInPinnedNetwork", "Effect": "Allow", "Action": "ec2:CreateVpcEndpoint", "Resource": supporting},
        {"Sid": "CreateOnlyTwoServices", "Effect": "Allow", "Action": "ec2:CreateVpcEndpoint", "Resource": endpoints_arn,
         "Condition": {"StringEquals": {"ec2:VpceServiceName": [e["ServiceName"] for e in endpoints], "aws:RequestTag/ManagedBy": OWNER}}},
        {"Sid": "TagOnlyAtCreation", "Effect": "Allow", "Action": "ec2:CreateTags", "Resource": endpoints_arn,
         "Condition": {"StringEquals": {"ec2:CreateAction": "CreateVpcEndpoint", "aws:RequestTag/ManagedBy": OWNER}}},
        {"Sid": "DeleteOnlyOriginalEndpoints", "Effect": "Allow", "Action": "ec2:DeleteVpcEndpoints",
         "Resource": [arn + "vpc-endpoint/" + e["VpcEndpointId"] for e in endpoints]},
        {"Sid": "DeleteOnlyOwnedEndpoints", "Effect": "Allow", "Action": "ec2:DeleteVpcEndpoints", "Resource": endpoints_arn,
         "Condition": {"StringEquals": {"ec2:ResourceTag/ManagedBy": OWNER, "ec2:ResourceTag/ManagedVpc": config["vpcId"],
                                        "ec2:VpceServiceName": [e["ServiceName"] for e in endpoints]}}},
        {"Sid": "WriteOwnLogStreams", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{NAME}:*"},
        {"Sid": "OwnOperationLock", "Effect": "Allow", "Action": ["dynamodb:PutItem", "dynamodb:DeleteItem"],
         "Resource": f"arn:aws:dynamodb:{region}:{account}:table/{LOCK_TABLE}",
         "Condition": {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["ssm-switch"]}}},
    ]
    # Inline CloudFormation Python is index.py; the original reviewed source and
    # config are embedded as literals. No S3 artifact upload or public URL needed.
    source = (HERE / "handler.py").read_text(encoding="utf-8")
    inline = source.replace('config = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))',
                            "config = json.loads(" + repr(json.dumps(config)) + ")")
    template = {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Manual SSM endpoint switch. No EC2 starts, schedules, URL, NAT or VPC attachment.",
        "Resources": {
            "Lock": {"Type": "AWS::DynamoDB::Table", "Properties": {"TableName": LOCK_TABLE, "BillingMode": "PAY_PER_REQUEST",
                "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}]}},
            "Logs": {"Type": "AWS::Logs::LogGroup", "Properties": {"LogGroupName": "/aws/lambda/" + NAME, "RetentionInDays": 7}},
            "Role": {"Type": "AWS::IAM::Role", "Properties": {
                "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
                "Policies": [{"PolicyName": "PinnedSsmEndpointsOnly", "PolicyDocument": {"Version": "2012-10-17", "Statement": statements}}]}},
            "Switch": {"Type": "AWS::Lambda::Function", "DependsOn": "Logs", "Properties": {
                "FunctionName": NAME, "Description": "Manual status/on/off for SSM only; off requires stopped EC2 and confirmation.",
                "Runtime": "python3.12", "Handler": "index.lambda_handler", "MemorySize": 256, "Timeout": 90,
                "Environment": {"Variables": {"LOCK_TABLE": {"Ref": "Lock"}}},
                "Role": {"Fn::GetAtt": ["Role", "Arn"]}, "Code": {"ZipFile": inline}}},
        },
        "Outputs": {"FunctionName": {"Value": {"Ref": "Switch"}}, "FunctionArn": {"Value": {"Fn::GetAtt": ["Switch", "Arn"]}}}}
    return template


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    template = build(json.loads(a.baseline.read_text(encoding="utf-8")))
    a.output.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"templateWritten": True, "resourceTypes": [r["Type"] for r in template["Resources"].values()], "awsMutations": False}))
