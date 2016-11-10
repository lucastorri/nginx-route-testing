#!/usr/bin/env python

import BaseHTTPServer
import yaml
import os
import glob
from threading import Thread
import re
import httplib
import shutil
import signal
import subprocess
import time


TEST_CONF = 'nginx-test.conf'
TEST_HOST = 'localhost'
TEST_PORT = 4443
TEST_SETTINGS = {
  'server_name': TEST_HOST
}

NGINX_WARMUP_TIME = 1

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


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
    conn.request(method, path, '')
    r = conn.getresponse()
    status = r.status
    conn.close()
    return status == 200

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


def load_test_suites():
  test_files = glob.glob(SCRIPT_DIR + '/*.test')

  suites = []
  for i, test_file in enumerate(test_files):
    with open(test_file, 'r') as file:
      suites.append(TestSuite(i, file))

  return suites


class bcolors:
  HEADER = '\033[95m'
  OKBLUE = '\033[94m'
  OKGREEN = '\033[92m'
  WARNING = '\033[93m'
  FAIL = '\033[91m'
  ENDC = '\033[0m'
  BOLD = '\033[1m'
  UNDERLINE = '\033[4m'


def report(success, test, msg=None):
  color = bcolors.OKGREEN if success else bcolors.FAIL
  title = '  OK' if success else 'FAIL'
  extra = '' if not msg else ' [' + msg + ']'
  print('[' + color + title + bcolors.ENDC + '] ' + str(test) + extra)


def run_tests(suites):
  success = True

  for suite in suites:
    suite.setup()

  all_tests = []
  for suite in suites:
    for test in suite.tests():
      all_tests.append(test)

  for test in all_tests:
    hit = test.run() and test.hit()
    other_hit = None
    for other_test in all_tests:
      if other_test.hit():
        other_hit = other_test
    if not hit:
      success = False
      if other_hit:
        report(False, test, 'hit {0} instead'.format(other_hit.suite.service))
      else:
        report(False, test, 'no hit')
    else:
      report(bcolors.OKGREEN, test)

  for suite in suites:
    suite.tear_down()

  return success


def replace_key(key, value, string):
  return re.sub('\\{\\{\\s*' + key + '\\s*\\}\\}', value, string)


def prepare_environment(suites):
  run_dir = SCRIPT_DIR + '/../_run'
  servers_dir = SCRIPT_DIR +'/../src/servers'
  test_config_file = SCRIPT_DIR + '/' + TEST_CONF

  shutil.rmtree(run_dir, ignore_errors = True)
  shutil.copytree(servers_dir, run_dir + '/servers')
  shutil.copy(test_config_file, run_dir)

  for config_file in glob.glob(run_dir + '/**/*'):
    if os.path.isfile(config_file):
      with open(config_file, 'r+') as file:
        data = file.read()
        for key, value in TEST_SETTINGS.iteritems():
          data = replace_key(key, value, data)
        for suite in suites:
          data = replace_key(suite.service, suite.url, data)
        file.seek(0)
        file.write(data)
        file.truncate()

  return run_dir + '/' + TEST_CONF


def run():
  suites = load_test_suites()
  config_file = prepare_environment(suites)
  with Nginx(config_file) as nginx:
    return run_tests(suites)


if __name__ == '__main__':
  success = run()
  exit(0 if success else 1)
