# -*- coding: utf-8 -*-
import base64
import datetime
import json
import os.path
import re
from pathlib import Path
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import googleapiclient.errors

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / 'cache'
os.makedirs(CACHE_DIR, exist_ok=True)
TMP_DIR = BASE_DIR / 'tmp'
os.makedirs(TMP_DIR, exist_ok=True)


class UnblockZh:
    user_id = 'me'
    maxResults = 500
    cacheThreads = False
    query = 'list:unblock-zh@lists.wikimedia.org'
    unblockZhLabelName = None
    threads = []

    def __init__(self):
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file(BASE_DIR / 'token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(BASE_DIR / 'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        self.service = build('gmail', 'v1', credentials=creds)

    def getLabel(self):
        if self.unblockZhLabelName is None:
            print('unblockZhLabelName is not set.')
            return

        results = self.service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        self.unblockZhLabelId = None

        if not labels:
            print('No labels found.')
            return

        for label in labels:
            if label['name'] == self.unblockZhLabelName:
                self.unblockZhLabelId = label['id']
                return

    def loadThreads(self):
        path = CACHE_DIR / 'threads.json'
        if os.path.exists(path) and self.cacheThreads:
            with open(path, 'r', encoding='utf8') as f:
                self.threads = json.load(f).get('threads', [])
            return

        print('Querying threads')
        if self.unblockZhLabelName is None:
            tmp = self.service.users().threads().list(userId=self.user_id, q=self.query, maxResults=self.maxResults).execute()
        else:
            self.getLabel()
            tmp = self.service.users().threads().list(userId=self.user_id, labelIds=self.unblockZhLabelId, maxResults=self.maxResults).execute()

        with open(path, 'w', encoding='utf8') as f:
            json.dump(tmp, f, ensure_ascii=False, indent=4)

        self.threads = tmp.get('threads', [])

    def loadThreadsContent(self):
        for thread in self.threads:
            self.getThread(thread['id'])

    def getThread(self, threadId):
        path = CACHE_DIR / '{}.json'.format(threadId)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf8') as f:
                return json.load(f)

        print('Querying thread {}'.format(threadId))
        try:
            tdata = self.service.users().threads().get(userId=self.user_id, id=threadId).execute()
        except googleapiclient.errors.HttpError as e:
            return None

        with open(path, 'w', encoding='utf8') as f:
            json.dump(tdata, f, ensure_ascii=False, indent=4)

        return tdata

    def parseThread(self, tdata):
        nmsgs = len(tdata['messages'])

        msg = tdata['messages'][0]['payload']
        result = {
            'id': tdata['id'],
            'messages': []
        }
        for msg in tdata['messages']:
            msgdata = {
                'id': msg['id'],
            }

            dt = datetime.datetime.fromtimestamp(int(msg['internalDate']) / 1000)
            msgdata['time'] = str(dt)

            for header in msg['payload']['headers']:
                if header['name'] == 'Subject':
                    msgdata['subject'] = header['value']
                elif header['name'] == 'Archived-At':
                    msgdata['archiveAt'] = header['value'][1:-1]
                elif header['name'] == 'X-MailFrom':
                    msgdata['xMailFrom'] = header['value']
                elif header['name'] == 'From':
                    m = re.search(r'^(.*?)? ?<(.+?)>$', header['value'])
                    if m:
                        msgdata['fromName'] = m.group(1)
                        msgdata['fromAddress'] = m.group(2)
            msgdata['text'] = '\n'.join(self.parseMessageParts(msg['payload']))

            path = TMP_DIR / '{}-{}.txt'.format(tdata['id'], msg['id'])
            with open(path, 'w', encoding='utf8') as f:
                f.write(msgdata['text'])

            path = TMP_DIR / '{}-{}.json'.format(tdata['id'], msg['id'])
            with open(path, 'w', encoding='utf8') as f:
                json.dump(msgdata, f, ensure_ascii=False, indent=4)

            result['messages'].append(msgdata)

        return result

    def parseMessageParts(self, part):
        res = []
        if part['mimeType'] == 'text/plain':
            if part['body']['size'] > 0:
                try:
                    tmp = base64.urlsafe_b64decode(part['body']['data']).decode('utf8')
                except:
                    tmp = 'DECODING ERROR'
                tmp = re.sub(r'\r\n', '\n', tmp)
                res.append(tmp)
        elif part['mimeType'] == 'text/html':
            if part['body']['size'] > 0:
                try:
                    tmp = base64.urlsafe_b64decode(part['body']['data']).decode('utf8')
                except:
                    tmp = 'DECODING ERROR'
                soup = BeautifulSoup(tmp, 'html.parser')
                tmp = soup.text
                tmp = re.sub(r'\r\n', '\n', tmp)
                res.append(tmp)
        if 'parts' in part:
            for subpart in part['parts']:
                res.extend(self.parseMessageParts(subpart))
        return res

    def main(self):
        self.loadThreads()

        for thread in self.threads:
            tdata = self.getThread(thread['id'])
            print('{} - {}'.format(thread['id'], tdata['messages'][0]['snippet']))


if __name__ == '__main__':
    unblockZh = UnblockZh()
    unblockZh.maxResults = 3
    unblockZh.main()
