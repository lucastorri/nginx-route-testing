#!/usr/bin/env python

import os
import re
import glob
import time
import yaml
import shutil
import signal
import httplib
import subprocess
import BaseHTTPServer
from threading import Thread


TEST_HOST = 'localhost'
TEST_PORT = 7000
TEST_SETTINGS = {
  'server_name': TEST_HOST
}

NGINX_WARMUP_TIME = 1

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
RUN_DIR = SCRIPT_DIR + '/../_run'
SERVERS_DIR = SCRIPT_DIR +'/../src/servers'
TEST_CONFIG_FILE = SCRIPT_DIR + '/nginx-test.conf'


class Handler(BaseHTTPServer.BaseHTTPRequestHandler):

  def handle_one_request(self):
    self.server.request_received = True
    self.raw_requestline = self.rfile.readline(1024)
    if not self.parse_request():
      return
    self.protocol_version = '1.1'
    self.send_response(200)
    self.wfile.flush()

  def log_message(self, format, *args):
    pass


class Server:

  def __init__(self, port):
    self.server = BaseHTTPServer.HTTPServer(('localhost', port), Handler)
    self.server.request_received = False
    self.thread = Thread(target = self._run)

  def start(self):
    self.thread.start()

  def _run(self):
    try:
      self.server.serve_forever()
    except Exception:
      pass

  def request_received(self):
    return self.server.request_received

  def reset(self):
    self.server.request_received = False

  def stop(self):
    self.server.server_close()
    self.thread.join()


class Test:

  def __init__(self, suite, description):
    self.suite = suite
    self.description = description

  def run(self):
    match = re.match('(\w+)\s+(.*)', self.description)
    method = match.group(1)
    path = match.group(2)

    conn = httplib.HTTPConnection('{0}:{1}'.format(TEST_HOST, TEST_PORT))
    conn.request(method, path)
    r = conn.getresponse()
    conn.close()
    return r.status == 200

  def hit(self):
    hit = self.suite.server.request_received()
    self.suite.server.reset()
    return hit

  def __str__(self):
    return self.description + ' -> ' + self.suite.service

  def __repr__(self):
    return self.__str__()


class TestSuite:

  def __init__(self, number, file):
    self.file = file
    data = yaml.load(file)
    self.service = data['service']
    self.tests_description = data['tests']
    self.port = 8000 + number
    self.url = 'http://localhost:{0}'.format(self.port)
    self.server = Server(self.port)

  def setup(self):
    self.server.start()

  def tests(self):
    return map(lambda t: Test(self, t), self.tests_description)

  def tear_down(self):
    self.server.stop()


class Nginx:

  def __init__(self, config_file):
    self.config_file = config_file

  def __enter__(self):
    self.start()
    return self

  def __exit__(self, type, value, traceback):
    self.stop()

  def start(self):
    try:
      self.pro = subprocess.Popen('nginx -c ' + self.config_file, stdout = subprocess.PIPE, shell = True, preexec_fn = os.setsid)
      time.sleep(NGINX_WARMUP_TIME)
      os.getpgid(self.pro.pid)
    except Exception:
      exit(1)

  def stop(self):
    os.killpg(os.getpgid(self.pro.pid), signal.SIGTERM)


class Console:

  HEADER = '\033[95m'
  OKBLUE = '\033[94m'
  OKGREEN = '\033[92m'
  WARNING = '\033[93m'
  FAIL = '\033[91m'
  ENDC = '\033[0m'
  BOLD = '\033[1m'
  UNDERLINE = '\033[4m'

  @staticmethod
  def report(success, test, msg=None):
    color = Console.OKGREEN if success else Console.FAIL
    title = '  OK' if success else 'FAIL'
    extra = '' if not msg else ' [' + msg + ']'
    print('[' + color + title + Console.ENDC + '] ' + str(test) + extra)


def load_test_suites():
  test_files = glob.glob(SCRIPT_DIR + '/*.test')

  suites = []
  for i, test_file in enumerate(test_files):
    with open(test_file, 'r') as file:
      suites.append(TestSuite(i, file))

  return suites


def run_tests(suites):
  success = True

  for suite in suites:
    suite.setup()

  all_tests = [test for suite in suites for test in suite.tests()]

  for test in all_tests:
    hit = test.run() and test.hit()
    other_hit = None
    for other_test in all_tests:
      if other_test.hit():
        other_hit = other_test
    if not hit:
      success = False
      if other_hit:
        Console.report(False, test, 'hit {0} instead'.format(other_hit.suite.service))
      else:
        Console.report(False, test, 'no hit')
    else:
      Console.report(True, test)

  for suite in suites:
    suite.tear_down()

  return success


def replace_key(key, value, string):
  return re.sub('\\{\\{\\s*' + key + '\\s*\\}\\}', value, string)


def render_file(path, suites):
  with open(path, 'r+') as file:
    data = file.read()
    for key, value in TEST_SETTINGS.iteritems():
      data = replace_key(key, value, data)
    for suite in suites:
      data = replace_key(suite.service, suite.url, data)
    file.seek(0)
    file.write(data)
    file.truncate()


def prepare_environment(suites):
  shutil.rmtree(RUN_DIR, ignore_errors = True)
  shutil.copytree(SERVERS_DIR, RUN_DIR + '/servers')
  shutil.copy(TEST_CONFIG_FILE, RUN_DIR)

  for config_file in glob.glob(RUN_DIR + '/**/*'):
    if os.path.isfile(config_file):
      render_file(config_file, suites)

  return RUN_DIR + '/' + os.path.basename(TEST_CONFIG_FILE)


def run():
  suites = load_test_suites()
  config_file = prepare_environment(suites)
  with Nginx(config_file) as nginx:
    return run_tests(suites)


if __name__ == '__main__':
  success = run()
  exit(0 if success else 1)
