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

from __future__ import print_function
from collections import defaultdict
from botocore.exceptions import ClientError
from botocore.vendored import requests
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
import datetime
import operator
import boto3
import datetime
import logging
import os
import re


class EmailBot:

    def __init__(self, img_file="/tmp/img_file.png", sla_days=5,
                 github_user = os.environ.get("github_user"),
                 github_oauth_token = os.environ.get("github_oauth_token"),
                 repo = os.environ.get("repo"),
                 sender = os.environ.get("sender"),
                 recipients = os.environ.get("recipients"),
                 aws_region = os.environ.get('aws_region'),
                 elastic_beanstalk_url = os.environ.get("eb_url")):
        """
        This EmailBot serves to send github issue reports to recipients.
        Args:
            img_file(str): the path of image file which will be attached in email content
            github_user(str): the github id. ie: "CathyZhang0822"
            github_oauth_token(str): the github oauth token, paired with github_user to realize authorization
            repo(str): the repo name
            sender(str): sender's email address must be verifed in AWS SES. ie:"a@email.com"
            recipients(str): recipients' email address must be verified in AWS SES. ie:"a@email.com, b@email.com"
            aws_region(str): aws region. ie:"us-east-1"
            elastic_beanstalk_url: the url of EB web server
        """
        self.github_user = github_user
        self.github_oauth_token = github_oauth_token
        self.repo = repo
        self.auth = (self.github_user, self.github_oauth_token)
        self.sender = sender
        self.recipients = [s.strip() for s in recipients.split(",")] if recipients else None
        self.aws_region = aws_region
        self.elastic_beanstalk_url = elastic_beanstalk_url if elastic_beanstalk_url[-1]!="/" else elastic_beanstalk_url[:-1]
        self.img_file = img_file
        self.open_issues = None
        self.closed_issues = None
        self.sorted_open_issues = None
        self.start = datetime.datetime.strptime("2015-01-01", "%Y-%m-%d")
        self.end = datetime.datetime.today()+datetime.timedelta(days=2)
        self.sla_days = sla_days
        # 2018-5-15 is the date that 'issues outside sla' concept was used.
        self.sla_start = datetime.datetime.strptime("2018-05-15", "%Y-%m-%d")

    def __clean_string(self, raw_string, sub_string):
        """
        This method is to convert all non-alphanumeric characters from raw_string to sub_string
        """
        cleans = re.sub("[^0-9a-zA-Z]", sub_string, raw_string)
        return cleans.lower()

    def __set_period(self, period_days):
        """
        This method is to set the time period. ie: set_period(7)
        Because GitHub use UTC time, so we set self.end 2 days after today's date
        For example:
        self.today = "2018-07-10 00:00:00"
        self.end = "2018-07-12 00:00:00"
        self.start = "2018-07-04 00:00:00"
        """
        today = datetime.datetime.strptime(str(datetime.datetime.today().date()), "%Y-%m-%d")
        self.end = today + datetime.timedelta(days=2)
        timedelta = datetime.timedelta(days=period_days)
        self.start = self.end - timedelta

    def __count_pages(self, obj, state='all'):
        """
        This method is to count how many pages of issues/labels in total
        obj could be "issues"/"labels"
        state could be "open"/"closed"/"all", available to issues
        """
        assert obj in set(["issues", "labels"]), "Invalid Input!"
        url = 'https://api.github.com/repos/{}/{}'.format(self.repo, obj)
        if obj == 'issues':
            response = requests.get(url, {'state': state},
                                    auth=self.auth)
        else:
            response = requests.get(url, auth=self.auth)
        assert response.status_code == 200, response.status_code
        if "link" not in response.headers:
            # That means only 1 page exits
            return 1
        # response.headers['link'] will looks like:
        # <https://api.github.com/repositories/34864402/issues?state=all&page=387>; rel="last"
        # In this case we need to extrac '387' as the count of pages
        return int(self.__clean_string(response.headers['link'], " ").split()[-3])

    def read_repo(self, periodically=True, period_days=8):
        """
        This method is to read issues in the repo.
        if periodically == True, it will read issues which are created in a specific time period
        if periodically == False, it will read all issues
        """
        logging.info("Start reading {} issues".format("periodically" if periodically else "all"))
        if periodically:
            self.__set_period(period_days)
        else:
            self.start = self.sla_start
            self.end = datetime.datetime.today()+datetime.timedelta(days=2)
        pages = self.__count_pages('issues', 'all')
        open_issues = []
        closed_issues = []
        # nested function to help break out of multiple loops
        def read_issues(response):
            for item in response.json():
                if "pull_request" in item:
                    continue
                created = datetime.datetime.strptime(item['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                if self.start <= created <= self.end:
                    if item['state'] == 'open':
                        open_issues.append(item)
                    elif item['state'] == 'closed':
                        closed_issues.append(item)
                else:
                    return True
            return False

        for page in range(1, pages + 1):
            url = 'https://api.github.com/repos/' + self.repo + '/issues?page=' + str(page) \
                  + '&per_page=30'.format(repo=self.repo)
            response = requests.get(url,
                                    {'state': 'all',
                                     'base': 'master',
                                     'sort': 'created',
                                     'direction': 'desc'},
                                    auth=self.auth)
            response.raise_for_status()
            if read_issues(response):
                break
        self.open_issues = open_issues
        self.closed_issues = closed_issues

    def sort(self):
        """
        This method is to sort open issues.
        Returns a dictionary.
        """
        assert self.open_issues, "No open issues in this time period!"
        items = self.open_issues
        labelled = []
        labelled_urls = ""
        unlabelled = []
        unlabelled_urls = ""
        labels = {}
        labels = defaultdict(lambda: 0, labels)
        non_responded = []
        non_responded_urls = ""
        outside_sla = []
        outside_sla_urls = ""
        responded = []
        responded_urls = ""
        total_deltas = []

        for item in items:
            url = "<a href='" + item['html_url'] + "'>" + str(item['number']) + "</a>   "
            created = datetime.datetime.strptime(item['created_at'], "%Y-%m-%dT%H:%M:%SZ")
            if item['labels']:
                labelled += [{k: v for k, v in item.items()
                              if k in ['number', 'html_url', 'title']}]
                labelled_urls = labelled_urls + url
                for label in item['labels']:
                    labels[label['name']] += 1
            else:
                unlabelled += [{k: v for k, v in item.items()
                                if k in ['number', 'html_url', 'title']}]
                unlabelled_urls = unlabelled_urls + url
            if item['comments'] == 0:
                non_responded += [{k: v for k, v in item.items()
                                   if k in ['number', 'html_url', 'title']}]
                non_responded_urls = non_responded_urls + url
                if self.sla_start < created < datetime.datetime.now() - datetime.timedelta(days=self.sla_days):
                    outside_sla += [{k: v for k, v in item.items()
                                     if k in ['number', 'html_url', 'title']}]
                    outside_sla_urls = outside_sla_urls + url
            else:
                responded += [{k: v for k, v in item.items()
                               if k in ['number', 'html_url', 'title']}]
                responded_urls = responded_urls + url
                comments_url = item['comments_url']
                comments = requests.get(comments_url, auth=self.auth)
                first_comment_created = datetime.datetime.strptime(comments.json()[0]['created_at'],
                                                                   "%Y-%m-%dT%H:%M:%SZ")
                delta = first_comment_created - created
                total_deltas.append(delta)
        labels['unlabelled'] = len(unlabelled)
        sorted_open_issues = {"labelled": labelled,
                "labels" : labels,
                "labelled_urls": labelled_urls,
                "unlabelled": unlabelled,
                "unlabelled_urls": unlabelled_urls,
                "responded": responded,
                "responded_urls": responded_urls,
                "non_responded": non_responded,
                "non_responded_urls": non_responded_urls,
                "outside_sla": outside_sla,
                "outside_sla_urls": outside_sla_urls,
                "total_deltas": total_deltas}
        self.sorted_open_issues = sorted_open_issues
        return sorted_open_issues

    def predict(self):
        """
        This method is to send POST requests to EB web server.
        Then EB web server will send predictions of unlabeled issues back.
        Returns a json:
        ie: [{"number":11919, "predictions":["doc"]}]
        """
        assert self.sorted_open_issues, "Please sort open issues first"
        issues = self.sorted_open_issues
        unlabeled_issue_number = [item['number'] for item in issues["unlabelled"]]
        logging.info("Start predicting labels for: {}".format(str(unlabeled_issue_number)))
        url = "{}/predict".format(self.elastic_beanstalk_url)
        response = requests.post(url, json={"issues": unlabeled_issue_number})
        logging.info(response.json())
        return response.json()

   

    def __html_table(self, lol):
        """
        This method is to generate html table.
        Args:
            lol(list of lists): table content
        """
        yield '<table style="width: 500px;">'
        for sublist in lol:
            yield '  <tr><td style = "width:200px;">'
            yield '    </td><td style = "width:300px;">'.join(sublist)
            yield '  </td></tr>'
        yield '</table>'

    def __bodyhtml(self):
        """
        This method is to generate body html of email content
        """
        self.read_repo(False)
        all_sorted_open_issues = self.sort()
        self.read_repo(True)
        weekly_sorted_open_issues = self.sort()
        # draw the pie chart
        all_labels = weekly_sorted_open_issues['labels']
        sorted_labels = sorted(all_labels.items(), key=operator.itemgetter(1), reverse=True)
        labels = [item[0] for item in sorted_labels[:10]]
        fracs = [item[1] for item in sorted_labels[:10]]
        url = "{}/draw".format(self.elastic_beanstalk_url)
        pic_data = {"fracs": fracs, "labels": labels}
        response = requests.post(url, json=pic_data)
        if response.status_code == 200:
            with open(self.img_file, "wb") as f:
                f.write(response.content)
        # generate the first html table
        total_deltas = weekly_sorted_open_issues["total_deltas"]
        if len(total_deltas) != 0:
            avg = sum(total_deltas, datetime.timedelta())/len(total_deltas)
            avg_time = str(avg.days)+" days, "+str(int(avg.seconds/3600))+" hours"
            worst_time = str(max(total_deltas).days)+" days, "+str(int(max(total_deltas).seconds/3600)) + " hours"
        else:
            avg_time = "N/A"
            worst_time = "N/A"
        htmltable = [
                    ["Count of labeled issues:", str(len(weekly_sorted_open_issues["labelled"]))],
                    ["Count of unlabeled issues:", str(len(weekly_sorted_open_issues["unlabelled"]))],
                    ["List unlabeled issues", weekly_sorted_open_issues["unlabelled_urls"]],
                    ["Count of issues with response:", str(len(weekly_sorted_open_issues["responded"]))],
                    ["Count of issues without response:", str(len(weekly_sorted_open_issues["non_responded"]))],
                    ["The average response time is:", avg_time],
                    ["The worst response time is:", worst_time],
                    ["List issues without response:", weekly_sorted_open_issues["non_responded_urls"]],
                    ["Count of issues without response within 5 days:", str(len(all_sorted_open_issues["outside_sla"]))],
                    ["List issues without response with 5 days:", all_sorted_open_issues["outside_sla_urls"]]]
        # generate the second html tabel
        htmltable2 = [["<a href='" +"https://github.com/{}/issues/{}".format(self.repo,str(item['number']) ) + "'>" + str(item['number']) + "</a>   ", 
                       ",".join(item['predictions'])] for item in self.predict()]
        body_html = """<html>
        <head>
        </head>
        <body>
          <h4>Week: {} to {}</h4>
          <p>{} newly issues were opened in the above period, among which {} were closed and {} are still open.</p>
          <div>{}</div>
          <p>Here are the recommanded labels for unlabeled issues:</p>
          <div>{}</div>
          <p><img src="cid:image1" width="400" height="400"></p>
        </body>
        </html>
                    """.format(str(self.start.date()), str((self.end - datetime.timedelta(days=2)).date()),
                               str(len(self.open_issues) + len(self.closed_issues)),
                               str(len(self.closed_issues)), str(len(self.open_issues)),
                               "\n".join(self.__html_table(htmltable)),
                               "\n".join(self.__html_table(htmltable2)))
        return body_html

    def sendemail(self):
        """
        This method is to send emails.
        The email content contains 2 html tables and an image.
        """
        sender = self.sender
        recipients = self.recipients
        aws_region = self.aws_region
        # The email body for recipients with non-HTML email clients.
        body_text = "weekly report"
        # The HTML body of the email.
        body_html = self.__bodyhtml()
        # The subject line for the email.
        subject = "GitHub Issues Daily Report {} to {}".format(str(self.start.date()),
                                                               str((self.end - datetime.timedelta(days=2)).date()))
        # The character encoding for the email.
        charset = "utf-8"
        # Create a new SES resource and specify a region.
        client = boto3.client('ses', region_name=aws_region)

        # Create a multipart/mixed parent container.
        msg = MIMEMultipart('mixed')
        # Add subject, from and to lines
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ",".join(recipients)

        # Create a multiparter child container
        msg_body = MIMEMultipart('alternative')

        # Encode the text and HTML content and set the character encoding. This step is
        # necessary if you're sending a message with characters outside the ASCII range.
        textpart = MIMEText(body_text.encode(charset), 'plain', charset)
        htmlpart = MIMEText(body_html.encode(charset), 'html', charset)

        # Add the text and HTML parts to the child container
        msg_body.attach(textpart)
        msg_body.attach(htmlpart)
        msg.attach(msg_body)

        # Attach Image
        fg = open(self.img_file, 'rb')
        msg_image = MIMEImage(fg.read())
        fg.close()
        msg_image.add_header('Content-ID', '<image1>')
        msg.attach(msg_image)

        try:
            # Provide the contents of the email.
            response = client.send_raw_email(
                Source=sender,
                Destinations=recipients,
                RawMessage={
                    'Data': msg.as_string(),
                },
            )
            logging.info("Email sent! Message ID:")
            logging.info(response['MessageId'])
        # Display an error if something goes wrong.
        except ClientError as e:
            logging.exception(e.response['Error']['Message'])
