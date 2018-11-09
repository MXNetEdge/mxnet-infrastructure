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
import boto3
from botocore.vendored import requests
from botocore.exceptions import ClientError
from LabelBot import LabelBot
import unittest

# some version issue
try:
    from unittest.mock import patch
except ImportError:
    from mock import patch


class TestLabelBot(unittest.TestCase):
    """
    Unittest of LabelBot.py
    """
    def setUp(self):
        self.lb = LabelBot(repo="harshp8l/mxnet-infrastructure",  apply_secret=True)

    def test_add_labels(self):
        with patch('LabelBot.requests.post') as mocked_post:
            mocked_post.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.add_labels(issue_num=0, labels=['sample_label']))

    def test_remove_labels(self):
        with patch('LabelBot.requests.delete') as mocked_delete:
            mocked_delete.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.remove_labels(issue_num=0, labels=['sample_label']))

    def test_update_labels(self):
        with patch('LabelBot.requests.put') as mocked_put:
            mocked_put.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.update_labels(issue_num=0, labels=['sample_label']))

    # Tests for different types of labels
    def test_tokenize(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[Sample Label]")
        self.assertEqual(user_label, ['sample label'])

    def test_tokenize2(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[sAMpLe LAbEl, another Label, fInal]")
        self.assertEqual(user_label, ['sample label', 'another label', 'final'])

    def test_tokenize3(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[Sample Label, label2, label3]")
        self.assertEqual(user_label, ['sample label', 'label2', 'label3'])

    def test_tokenize4(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[Good first issue]")
        self.assertEqual(user_label, ['good first issue'])

    def test_tokenize5(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[MANY many wORds hERe are THere, hello GOODbye ok]")
        self.assertEqual(user_label, ['many many words here are there', 'hello goodbye ok'])


if __name__ == "__main__":
    unittest.main()
