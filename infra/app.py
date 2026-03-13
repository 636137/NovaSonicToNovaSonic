#!/usr/bin/env python3
import os
from aws_cdk import App, Environment
from cdk.connect_stack import ConnectCensusStack

app = App()

env = Environment(
    account=os.environ.get('CDK_DEFAULT_ACCOUNT'),
    region=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
)

ConnectCensusStack(app, "ConnectCensusStack", env=env)

app.synth()
