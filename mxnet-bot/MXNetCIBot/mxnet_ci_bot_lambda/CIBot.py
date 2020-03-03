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
import logging
import secret_manager
import hmac
import hashlib
from jenkinsapi.jenkins import Jenkins

import requests
from github import Github

class CIBot:
    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_user=None,
                 github_personal_access_token=None,
                #  bot_user=None,
                #  bot_oauth_token=None,
                 apply_secret=True):
        """
        Initializes the CI Bot
        :param repo: GitHub repository that is being referenced
        :param github_user: GitHub username
        :param github_personal_access_token: GitHub authentication token (Personal access token)
        :param apply_secret: GitHub secret credential (Secret credential that is unique to a GitHub developer)
        """
        self.repo = repo
        self.github_user = github_user
        self.github_personal_access_token = github_personal_access_token
        # self.bot_user = bot_user
        # self.bot_oauth_token = bot_oauth_token
        if apply_secret:
            self._get_secret()
        self.auth = (self.github_user, self.github_personal_access_token)
        # self.bot_auth = (self.bot_user, self.bot_oauth_token)
        self.bot_auth = (self.github_user, self.github_personal_access_token)
        self.all_jobs = None
        self.jenkins_url = "http://jenkins.mxnet-ci-dev.amazon-ml.com/"
        self.jenkins_username = "ChaiBapchya"
        self.jenkins_password = "113b7958db9a24e95ff52705e096e4bec0"

    def _get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """        
        secret = json.loads(secret_manager.get_secret())
        self.github_user = secret["github_user"]
        self.github_personal_access_token = secret["github_personal_access_token"]
        self.webhook_secret = secret["webhook_secret"]
        # self.bot_user = secret["bot_user"]
        # self.bot_oauth_token = secret["bot_oauth_token"]        

    def _secure_webhook(self, event):
        """
        This method will validate the security of the webhook, it confirms that the secret
        of the webhook is matched and that each github event is signed appropriately
        :param event: The github event we want to validate
        :return Response denoting success or failure of security
        """

        # Validating github event is signed
        try:            
            git_signed = ast.literal_eval(event["Records"][0]['body'])['headers']["X-Hub-Signature"]
        except KeyError:
            raise Exception("WebHook from GitHub is not signed")
        git_signed = git_signed.replace('sha1=', '')

        # Signing our event with the same secret as what we assigned to github event
        secret = self.webhook_secret
        body = ast.literal_eval(event["Records"][0]['body'])['body']
        secret_sign = hmac.new(key=secret.encode('utf-8'), msg=body.encode('utf-8'), digestmod=hashlib.sha1).hexdigest()

        # Validating signatures match
        return hmac.compare_digest(git_signed, secret_sign)

    def _find_all_jobs(self):
        """
        This method finds out all the jobs that are currently supported as part of CI
        """
        # for now hardcoding list of jobs
        # ideally use Jenkins API to query list of jobs and parse it (bit complicated)
        all_jobs = ['clang', 'edge', 'centos-cpu', 'centos-gpu']
        self.all_jobs = set(all_jobs)

    def _trigger_job(self, jenkins_obj, name):
        job = jenkins_obj[name]
        logging.info(f'invoking {name}')
        try:
            job.invoke(block=False)
        except:
            raise Exception("unable to invoke job")

    def _get_jenkins_obj(self):
        logging.info(self.jenkins_url)
        logging.info(self.jenkins_username)
        logging.info(self.jenkins_password)
        return Jenkins(self.jenkins_url, username=self.jenkins_username, password = self.jenkins_password)

    def _trigger_ci(self, jobs, issue_num):
        """
        This method is responsible for triggering the CI
        :param payload: The payload required for passing to Jenkins CI
        :param jobs: The jobs to trigger CI
        :param issue_num: Number of the PR
        :response Response indicating success or failure of invoking Jenkins CI
        """

        # get jenkins credentials
        jenkins_obj = self._get_jenkins_obj()
        # invoke CI via jenkins api
        try:
            for job in jobs:
                self._trigger_job(jenkins_obj,"mxnet-validation/"+job+"/PR-"+str(issue_num))
        except:
            logging.error("Unexpected error")#, sys.exc_info()[0])
            raise Exception("Jenkins unable to trigger")
        return True

    def _get_github_object(self):
        github_obj = Github(self.github_personal_access_token)        
        return github_obj

    def _is_mxnet_committer(self, comment_author):
        """
        This method returns the list of MXNet committers
        It uses the Github API for fetching team members of a repo
        """
        github_obj = self._get_github_object()
        return github_obj.get_organization('apache').get_team(2413476).has_in_members(github_obj.get_user(comment_author))        

    def _is_authorized(self, comment_author, pr_author):
        # verify if the comment author is authorized to trigger CI
        # authorized users:
        # 1. PR Author
        # 2. MXNet Committer
        # 3. CI Admin
        # TODO : check for CI Admin
        if self._is_mxnet_committer(comment_author) or comment_author == pr_author:
            return True
        return False

    def _parse_jobs_from_comment(self, phrase):
        jobs=phrase.split(" ")[2:][0][1:-1].split(',')
        return jobs

    def parse_webhook_data(self, event):
        """
        This method triggers the CI bot when the appropriate
        GitHub event is recognized by use of a webhook
        :param event: The event data that is received whenever a PR comment is made
        :return: Log statements which we can track in lambda
        """
        try:
            github_event = ast.literal_eval(event["Records"][0]['body'])['headers']["X-GitHub-Event"]
            logging.info(f"github event {github_event}")
        except KeyError:
            raise Exception("Not a GitHub Event")

        if not self._secure_webhook(event):
            raise Exception("Failed to validate WebHook security")

        try:                        
            payload = json.loads(ast.literal_eval(event["Records"][0]['body'])['body'])
        except ValueError:
            raise Exception("Decoding JSON for payload failed")
        logging.info(f"payload loaded {payload}")
        # some times lambda is triggered (dont know coz of why)
        # it doesn't have payload[action]
        if(payload["action"] == 'deleted'):
            logging.info('comment deleted. Ignore')
            return
        
        # Grab actual payload data of the appropriate GitHub event needed for
        # triggering CI
        if github_event == "issue_comment":            
            # Look for phrase referencing @mxnet-ci-bot
            if "@MXNet-CI-Bot" in payload["comment"]["body"]:
                phrase = payload["comment"]["body"]#[payload["comment"]["body"].find("@MXNet-CI-Bot"):payload["comment"]["body"].find("]")+1]
                logging.info(phrase)
                # remove whitespace characters
                phrase = ' '.join(phrase.split())
                
                # Case so that ( run[job1] ) and ( run [job1] ) are treated the same way
                # if phrase.split(" ")[1].find('[') != -1:
                #     action = phrase.split(" ")[1][:phrase.split(" ")[1].find('[')].lower()
                # else:
                
                action = phrase.split(" ")[1].lower()
                logging.info(f'action {action}')
                issue_num = payload["issue"]["number"]
                if action not in ['run', 'trigger']:
                    message = "Undefined action detected. \n" \
                              "Permissible actions are : run, trigger \n" \
                              "Example : @mxnet-ci-bot run [centos-cpu] \n" \
                              "Example : @mxnet-ci-bot trigger [centos-gpu]"
                    self.create_comment(issue_num, message)
                    logging.error(f'Undefined action by user: {action}')
                    raise Exception("Undefined action by user")

                # parse jobs from the comment
                jobs = self._parse_jobs_from_comment(phrase)
                if not jobs:
                    logging.error(f'Message typed by user: {phrase}')
                    raise Exception("No jobs found from PR comment")

                # find all jobs currently run in CI
                self._find_all_jobs()
                if not self.all_jobs:
                    raise Exception("Unable to gather jobs from the CI")

                # check if any of the jobs requested by user are supported by CI
                if not set(jobs).intersection(set(self.all_jobs)):
                    logging.error(f'Jobs entered by user: {set(jobs)}')
                    logging.error(f'CI supported Jobs: {set(self.all_jobs)}')
                    message = "None of the jobs entered are supported. \n"
                            #   "Jobs entered by user:" + {set(jobs)}  \n" \
                            #   "Example : @mxnet-ci-bot run [centos-cpu] \n" \
                            #   "Example : @mxnet-ci-bot trigger [centos-gpu]"
                    self.create_comment(issue_num, message)
                    raise Exception("Provided jobs don't match the ones supported by CI")

                
                # check if the comment author is authorized
                comment_author = payload["comment"]["user"]["login"]
                pr_author = payload["issue"]["user"]["login"]

                if self._is_authorized(comment_author, pr_author):
                    logging.info(f'Authorized user: {comment_author}')
                    # since authorized user commented, go ahead trigger CI                    
                    if self._trigger_ci(jobs, issue_num):                        
                        message = "Jenkins CI successfully triggered."
                    else:
                        message = "Authorized user recognized. However, the bot is unable to trigger CI."
                    self.create_comment(issue_num, message)
                else:
                    # since unauthorized user tried to trigger CI
                    logging.info(f'Unauthorized user: {comment_author}')
                    message = "Unauthorized access detected. \n" \
                              "Only following 3 categories can trigger CI : \n" \
                              "PR Author, MXNet Committer, Jenkins Admin."
                    self.create_comment(issue_num, message)
        else:
            logging.info(f'GitHub Event unsupported by CI Bot: {github_event}')#{payload["action"]}

    def create_comment(self, issue_num, message):
        """
        This method will trigger a comment to an issue by the CI bot
        :param issue_num: The issue we want to comment
        :param message: The comment message we want to send
        :return Response denoting success or failure for logging purposes
        """
        send_msg = {"body": message}
        issue_comments_url = f'https://api.github.com/repos/{self.repo}/issues/{issue_num}/comments'

        response = requests.post(issue_comments_url, data=json.dumps(send_msg), auth=self.bot_auth)
        if response.status_code == 201:
            logging.info(f'Successfully commented {send_msg} to: {issue_num}')
            return True
        else:
            logging.error(f'Could not comment \n {json.dumps(response.json())}')
            return False