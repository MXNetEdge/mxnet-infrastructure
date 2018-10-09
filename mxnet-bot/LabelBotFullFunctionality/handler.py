# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# lambda handler
import os
import boto3
from LabelBot import LabelBot
import logging
logging.getLogger().setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
SQS_CLIENT = boto3.client('sqs')


def send_to_sqs(event, context):

    print(SQS_CLIENT.send_message(
        QueueUrl=os.getenv('SQS_URL'),
        MessageBody=str(event)
        ))

    # Successful response -- assuming message will be sent correctly to SQS
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": 'Success'
    }


def label_bot_lambda(event, context):
    lb = LabelBot(secret=True)
    remaining = lb.get_rate_limit()

    if remaining >= 4000:
        ret = lb.add_label(event)
        print(ret)
        data = lb.find_notifications()
        lb.label(data)
        remaining = lb.get_rate_limit()
        return "Lambda is triggered successfully! (remaining HTTP request: {})".format(remaining)
    else:
        return "Lambda failed triggered (out of limits: {})".format(remaining)

