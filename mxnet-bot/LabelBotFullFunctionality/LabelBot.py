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
from botocore.vendored import requests
import logging
import secret_manager


class LabelBot:

    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_user=None,
                 github_oauth_token=None,
                 secret=True):
        self.repo = repo
        self.github_user = github_user
        self.github_oauth_token = github_oauth_token
        if secret:
            self.get_secret()
        self.auth = (self.github_user, self.github_oauth_token)
        self.all_labels = None

    def get_rate_limit(self):
        res = requests.get('https://api.github.com/{}'.format('rate_limit'),
                           auth=self.auth)
        res.raise_for_status()
        data = res.json()['rate']
        return data['remaining']

    def get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """
        secret = json.loads(secret_manager.get_secret())
        self.github_user = secret["github_user"]
        self.github_oauth_token = secret["github_oauth_token"]

    def tokenize(self, string):
        """
        This method is to extract labels from comments
        """
        substring = string[string.find('[') + 1: string.rfind(']')]
        labels = [' '.join(label.split()) for label in substring.split(',')]
        return labels

    def count_pages(self, obj, state='open'):
        """
        This method is to count how many pages of issues/labels in total
        obj could be "issues"/"labels"
        state could be "open"/"closed"/"all", available to issues
        """
        assert obj in set(["issues", "labels"]), "Invalid Input!"
        url = 'https://api.github.com/repos/{}/{}'.format(self.repo, obj)
        if obj == 'issues':
            response = requests.get(url, {'state': state,
                                          'per_page': 100}, auth=self.auth)
        else:
            response = requests.get(url, auth=self.auth)
        response.raise_for_status()
        if "link" not in response.headers:
            return 1
        return int(self.clean_string(response.headers['link'], " ").split()[-3])

    def find_all_labels(self):
        """
        This method is to find all existing labels in the repo
        """
        pages = self.count_pages("labels")
        all_labels = []
        for page in range(1, pages + 1):
            url = 'https://api.github.com/repos/' + self.repo + '/labels?page=' + str(page) \
                  + '&per_page=30'.format(repo=self.repo)
            response = requests.get(url, auth=self.auth)
            for item in response.json():
                all_labels.append(item['name'].lower())
        self.all_labels = set(all_labels)
        return set(all_labels)

    def label(self, issues):
        """
        This method is to add labels to multiple issues
        Input is a json file: [{number:1, labels:[a,b]},{number:2, labels:[c,d]}]
        """
        self.find_all_labels()
        for issue in issues:
            self.add_github_labels(issue['issue'], issue['labels'])

    def format_labels(self, labels):
        """
        This method formats labels that a user specifies for a specific issue. This is meant
        to provide functionality for the operations on labels
        :param issue_num: The issue we want to label
        :param labels: The labels we want to format
        :return: Formatted labels to send for CRUD operations
        """
        assert self.all_labels, "Find all labels first"
        # clean labels, remove duplicated spaces. ex: "hello  world" -> "hello world"
        labels = [" ".join(label.split()) for label in labels]
        labels = [label for label in labels if label.lower() in self.all_labels]
        return labels

    def add_github_labels(self, issue_num, labels):
        """
        This method is to add a list of labels to one issue.
        First it will remove redundant white spaces from each label.
        Then it will check whether labels exist in the repo.
        At last, it will add existing labels to the issue
        """
        labels = self.format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels' \
            .format(repo=self.repo, id=issue_num)

        response = requests.post(issue_labels_url, json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info('Successfully added labels to {}: {}.'.format(str(issue_num), str(labels)))
        else:
            logging.error("Could not add the labels")
            logging.error(response.json())

    def remove_github_labels(self, issue_num, labels):
        """
        This method is to remove a list of labels to one issue.
        First it will remove redundant white spaces from each label.
        Then it will check whether labels exist in the repo.
        At last, it will remove existing labels to the issue
        """
        labels = self.format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels' \
            .format(repo=self.repo, id=issue_num)

        for label in labels:
            delete_label_url = issue_labels_url + label
            response = requests.delete(delete_label_url, auth=self.auth)
            if response.status_code == 200:
                logging.info('Successfully removed label to {}: {}.'.format(str(issue_num), str(label)))
            else:
                logging.error("Could not remove the labels")
                logging.error(response.json())

    def update_github_labels(self, issue_num, labels):
        """
        This method is to update a list of labels to one issue.
        First it will remove redundant white spaces from each label.
        Then it will check whether labels exist in the repo.
        At last, it will update existing labels to the issue
        """
        labels = self.format_labels(labels)
        issue_labels_url = 'https://api.github.com/repos/{repo}/issues/{id}/labels' \
            .format(repo=self.repo, id=issue_num)

        response = requests.put(issue_labels_url, data=json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info('Successfully updated labels to {}: {}.'.format(str(issue_num), str(labels)))
        else:
            logging.error("Could not update the labels")
            logging.error(response.json())

    def add_comment(self, issue_num, message):
        """
        This method will trigger a comment to an issue by the label bot
        :param issue_num: The issue we want to comment
        :param message: The comment message we want to send
        """
        send_msg = {"body": message}
        issue_comments_url = 'https://api.github.com/repos/{repo}/issues/{id}/comments' \
            .format(repo=self.repo, id=issue_num)

        response = requests.post(issue_comments_url, data=json.dumps(send_msg), auth=self.auth)
        if response.status_code == 201:
            logging.info('Successfully commented')
        else:
            logging.error("Could not comment")

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
            raise json.ParseError('Expected a GitHub event')
            return "Not a GitHub event"

        # Grabs actual payload data of the appropriate GitHub event needed for labelling
        if github_event == "issue_comment":
            payload = json.loads(ast.literal_eval(event["Records"][0]['body'])['body'])

            # Acquiring labels specific to this repo
            labels = []
            if "@mxnet-label-bot" in payload["comment"]["body"]:
                labels += self.tokenize(payload["comment"]["body"])
                self.find_all_labels()

                if "@mxnet-label-bot, add" in payload["comment"]["body"]:
                    self.add_github_labels(payload["issue"]["number"], labels)
                    return "Added labels successfully"

                elif "@mxnet-label-bot, remove" in payload["comment"]["body"]:
                    self.remove_github_labels(payload["issue"]["number"], labels)
                    return "Removed labels successfully"

                elif "@mxnet-label-bot, update" in payload["comment"]["body"]:
                    self.update_github_labels(payload["issue"]["number"], labels)
                    return "Updated labels successfully"

                else:
                    return "Unrecognized format for the mxnet-label-bot"
            else:
                return "Not a comment referencing the mxnet-label-bot"
        else:
            return "Not an issue comment"
