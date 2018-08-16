#!/bin/bash
# Script to deploy the label bot to our dev account
set -e

export AWS_PROFILE=mxnet-ci-dev
sls deploy
