#!/bin/bash
# Script to deploy the label bot to our dev account
set -e
export AWS_PROFILE=mxnet-ci-dev

dest_account="968277166688"
bot_account="139068448383"

sed "s/###HERE###/$dest_account/g" log-access-trust-policy.json-template > log-access-trust-policy.json
sed "s/###HERE###/$bot_account/g" log-access-policy.json-template > log-access-policy.json

aws iam create-role --role-name LabelBotLogAccessRole --assume-role-policy-document file://log-access-trust-policy.json
aws iam create-policy --policy-name LabelBotLogAccessPolicy --policy-document file://log-access-policy.json
aws iam attach-role-policy --policy-arn arn:aws:iam::$bot_account:policy/LabelBotLogAccessPolicy --role-name LabelBotLogAccessRole

sls deploy -v
