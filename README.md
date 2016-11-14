# nginx-route-testing

If you have your microservices behind an [API gateway](http://microservices.io/patterns/apigateway.html) using [nginx](https://www.nginx.com/resources/wiki/), it might be difficult to properly test the changes made in you configuration.

For instance, consider a nginx configuration like the following, where `{{ key }}` represents some string that will be replaced by a configuration management tool:

```
server {
  listen 7000;
  server_name {{ server_name }};

  location / { proxy_pass {{ service_1 }}; }
  location /something { proxy_pass {{ service_2 }}; }
}
```

Even if you have each downstream service running, it might be difficult to test that your routes are forwarding requests to the desired service.

This project is a small experiment that automates the testing of your routes, and is able to inform if they are valid or not.

Tests are described using a simple YAML syntax:

```yaml
service: service_1
tests:
  - POST /
  - GET /hello
```

**service** defines the configuration key to be replaced, and **tests** is a list of requests that once made should hit the defined service.

You can then run the tests with:

```bash
python2 "$project_dir/test/test.py"
[  OK] GET / -> service_1
[  OK] POST /hello -> service_2
```


## How it Works

The python script does the following:

1. gets all test files;
2. instantiates a fake HTTP server for each service;
3. renders the nginx configuration files in `src/servers` with the services described on these test files and their fakes;
4. starts nginx;
5. runs all declared tests and make sure that the correct one was hit for each request;
6. clean ups the environment and reports the results.
