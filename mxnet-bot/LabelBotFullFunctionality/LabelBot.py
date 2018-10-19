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
import ast
import json
import os
import re
from botocore.vendored import requests
import logging
import secret_manager


class LabelBot:
    LABEL_PAGE_PARSE = 30  # Limit for total labels per page to parse

    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_user=None,
                 github_oauth_token=None,
                 apply_secret=True):
        """
        Initializes the Label Bot
        :param repo: GitHub repository that is being referenced
        :param github_user: GitHub username
        :param github_oauth_token: GitHub authentication token (Personal access token)
        :param apply_secret: GitHub secret credential (Secret credential that is unique to a GitHub developer)
        """
        self.repo = repo
        self.github_user = github_user
        self.github_oauth_token = github_oauth_token
        if apply_secret:
            self._get_secret()
        self.auth = (self.github_user, self.github_oauth_token)
        self.all_labels = None

    def _get_rate_limit(self):
        """
        This method gets the remaining rate limit that is left from the GitHub API
        :return Remaining API requests left that GitHub will allow
        """
        res = requests.get('https://api.github.com/{}'.format('rate_limit'),
                           auth=self.auth)
        res.raise_for_status()
        data = res.json()['rate']
        return data['remaining']

    def _get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """
        secret = json.loads(secret_manager.get_secret())
        self.github_user = secret["github_user"]
        self.github_oauth_token = secret["github_oauth_token"]

    def _tokenize(self, string):
        """
        This method is to extract labels from comments
        :param string: String parsed from a GitHub comment
        :return Set of Labels which have been extracted
        """
        substring = string[string.find('[') + 1: string.rfind(']')]
        labels = [' '.join(label.split()) for label in substring.split(',')]
        return labels

    def _ascii_only(self, raw_string, sub_string):
        """
        This method is to convert all non-alphanumeric characters from raw_string to sub_string
        :param raw_string The original string messy string
        :param sub_string The string we want to convert to
        :return Fully converted string
        """
        converted_string = re.sub("[^0-9a-zA-Z]", sub_string, raw_string)
        return converted_string.lower()

    def _find_all_labels(self):
        """
        This method finds all existing labels in the repo
        :return A set of all labels which have been extracted from the repo
        """
        url = 'https://api.github.com/repos/{}/{}'.format(self.repo, "labels")
        response = requests.get(url, auth=self.auth)
        response.raise_for_status()

        # Getting total pages of labels present
        if "link" not in response.headers:
            pages = 1
        else:
            pages = int(self._ascii_only(response.headers['link'], " ").split()[-3])

        all_labels = []
        for page in range(1, pages + 1):
            url = 'https://api.github.com/repos/' + self.repo + '/labels?page=' + str(page) \
                  + '&per_page={}'.format(self.LABEL_PAGE_PARSE, repo=self.repo)
            response = requests.get(url, auth=self.auth)
            for item in response.json():
                all_labels.append(item['name'].lower())
        self.all_labels = set(all_labels)
        return set(all_labels)

    def _format_labels(self, labels):
        """
        This method formats labels that a user specifies for a specific issue. This is meant
        to provide functionality for the operations on labels
        :param labels: The messy labels inputted by the user which we want to format
        :return: Formatted labels to send for CRUD operations
        """
        assert self.all_labels, "Find all labels first"
        # clean labels, remove duplicated spaces. ex: "hello  world" -> "hello world"
        labels = [" ".join(label.split()) for label in labels]
        labels = [label for label in labels if label.lower() in self.all_labels]
        return labels

    def add_labels(self, issue_num, labels):
        """
        This method is to add a list of labels to one issue.
        It checks whether labels exist in the repo, and adds existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to add
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels' \
            .format(repo=self.repo, id=issue_num)

        response = requests.post(issue_labels_url, json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info('Successfully added labels to {}: {}.'.format(str(issue_num), str(labels)))
            return True
        else:
            logging.error('Could not add the labels to {}: {}. \nResponse: {}'
                          .format(str(issue_num), str(labels), json.dumps(response.json())))
            return False

    def remove_labels(self, issue_num, labels):
        """
        This method is to remove a list of labels to one issue.
        It checks whether labels exist in the repo, and removes existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to remove
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels/' \
            .format(repo=self.repo, id=issue_num)

        for label in labels:
            delete_label_url = issue_labels_url + label
            response = requests.delete(delete_label_url, auth=self.auth)
            if response.status_code == 200:
                logging.info('Successfully removed label to {}: {}.'.format(str(issue_num), str(label)))
            else:
                logging.error('Could not remove the label to {}: {}. \nResponse: {}'
                              .format(str(issue_num), str(label), json.dumps(response.json())))
                return False
        return True

    def update_labels(self, issue_num, labels):
        """
        This method is to update a list of labels to one issue.
        It checks whether labels exist in the repo, and updates existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to remove
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels' \
            .format(repo=self.repo, id=issue_num)

        response = requests.put(issue_labels_url, data=json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info('Successfully updated labels to {}: {}.'.format(str(issue_num), str(labels)))
            return True
        else:
            logging.error('Could not update the labels to {}: {}. \nResponse: {}'
                          .format(str(issue_num), str(labels), json.dumps(response.json())))
            return False

    def label_action(self, actions):
        """
        This method will perform an actions for the labels that are provided. This function delegates
        the appropriate action to the correct methods.
        :param actions: The action we want to take on the label
        :return Response denoting success or failure for logging purposes
        """
        if "add" in actions:
            return self.add_labels(actions["add"][0], actions["add"][1])
        elif "remove" in actions:
            return self.remove_labels(actions["remove"][0], actions["remove"][1])
        elif "update" in actions:
            return self.update_labels(actions["update"][0], actions["update"][1])
        else:
            return False

    def parse_webhook_data(self, event):
        """
        This method triggers the label bot when the appropriate
        GitHub event is recognized by use of a webhook
        :param event: The event data that is received whenever a github issue, issue comment, etc. is made
        :return: Log statements which we can track in lambda
        """
        try:
            github_event = ast.literal_eval(event["Records"][0]['body'])['headers']["X-GitHub-Event"]
        except KeyError:
            raise Exception("Not a GitHub Event")

        try:
            payload = json.loads(ast.literal_eval(event["Records"][0]['body'])['body'])
        except ValueError:
            raise Exception("Decoding JSON for payload failed")

        # Grabs actual payload data of the appropriate GitHub event needed for labelling
        if github_event == "issue_comment":

            # Acquiring labels specific to this repo
            labels = []
            actions = {}
            if "@mxnet-label-bot" in payload["comment"]["body"]:
                labels += self._tokenize(payload["comment"]["body"])
                if not labels:
                    raise Exception("Unable to gather labels from issue comments")

                self._find_all_labels()
                if not self.all_labels:
                    raise Exception("Unable to gather labels from the repo")
                for label in labels:
                    if label not in self.all_labels:
                        raise Exception("Provided labels don't match labels from the repo")

                action = payload["comment"]["body"].split(" ")[1]
                issue_num = payload["issue"]["number"]
                actions[action] = issue_num, labels
                if not self.label_action(actions):
                    raise Exception("Unrecognized label action for the mxnet-label-bot")

        else:
            logging.error("GitHub Event unsupported by Label Bot")

