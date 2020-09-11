#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys

import ruamel.yaml
from ruamel.yaml import YAML

from pprint import pprint

SPANDX_TEMPLATE = '''/*global module, process*/
const localhost = (process.env.PLATFORM === 'linux') ? 'localhost' : 'host.docker.internal';

module.exports = {
    routes: {
        '/apps/automation-analytics': { host: `FRONTEND` },
        '/ansible/automation-analytics': { host: `FRONTEND` },
        '/beta/ansible/automation-analytics': { host: `FRONTEND` },
        '/api/tower-analytics': { host: `BACKEND` },
        '/apps/chrome': { host: `http://chrome` },
        '/apps/landing': { host: `http://landing` },
        '/beta/apps/landing': { host: `http://landing_beta` },
        '/api/entitlements': { host: `http://entitlements` },
        '/api/rbac': { host: `http://rbac` },
        '/beta/config': { host: `http://${localhost}:8889` },
        '/': { host: `http://webroot` }
    }
};
'''

ENTITLEMENTS_SERVER = '''#/usr/bin/env python3

import os

import flask
from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect


app = Flask(__name__)


services = [
    'ansible',
    'cost_management',
    'insights',
    'migrations',
    'openshift',
    'settings',
    'smart_management',
    'subscriptions',
    'user_preferences'
]


entitlements = {}
for svc in services:
    entitlements[svc] = {'is_entitled': True, 'is_trial': False}


rbac = {
    'meta': {'count': 30, 'limit': 1000, 'offset': 0},
    'links': {
        'first': '/api/rbac/v1/access/?application=&format=json&limit=1000&offset=0',
        'next': None,
        'previous': None,
        'last': '/api/rbac/v1/access/?application=&format=json&limit=1000&offset=0',
    },
    'data': [
        {'resourceDefinitions': [], 'permission': 'insights:*:*'}
    ]
}


@app.route('/api/entitlements/v1/services')
def services():
    return jsonify(entitlements)


@app.route('/api/rbac/v1/access/')
def rbac_access():
    return jsonify(rbac)


if __name__ == '__main__':
    if os.environ.get('API_SECURE'):
        app.run(ssl_context='adhoc', host='0.0.0.0', port=443, debug=True)
    else:
        app.run(host='0.0.0.0', port=80, debug=True)
'''

FLASKDOCKERFILE = '''FROM python:3
COPY requirements.txt /.
RUN pip install -r /requirements.txt
WORKDIR /app
CMD python3 api.py
'''

FLASKREQUIREMENTS = '''flask
cryptography
'''

class CloudBuilder:
    webroot = "www"
    checkouts_root = "src"
    cache_root = "cache"
    keycloak = "https://172.19.0.3:8443"
    frontend = "https://192.168.122.81:8002"
    backend = "http://192.168.122.81:5000"

    def __init__(self):
        if not os.path.exists(self.checkouts_root):
            os.makedirs(self.checkouts_root)
        if not os.path.exists(self.cache_root):
            os.makedirs(self.cache_root)
        if not os.path.exists(self.webroot):
            os.makedirs(self.webroot)

    def create_compose_file(self):
        ds = {
            'version': '3',
            'services': {
                'insights_proxy': {
                    'container_name': 'insights_proxy',
                    'image': 'redhatinsights/insights-proxy',
                    'ports': ['1337:1337'],
                    'environment': ['PLATFORM=linux', 'CUSTOM_CONF=true'],
                    'security_opt': ['label=disable'],
                    'extra_hosts': ['prod.foo.redhat.com:127.0.0.1'],
                    'volumes': ['./www/spandx.config.js:/config/spandx.config.js']
                },
                'webroot': {
                    'container_name': 'webroot',
                    'image': 'nginx',
                    'volumes': ["./www:/usr/share/nginx/html"],
                    #'volumes': [f"./{os.path.join(self.checkouts_root, 'landing-page-frontend', 'dist')}:/usr/share/nginx/html"],
                    'command': ['nginx-debug', '-g', 'daemon off;']
                },
                'chrome': {
                    'container_name': 'chrome',
                    'image': 'nginx',
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'insights-chrome')}:/usr/share/nginx/html"],
                    'command': ['nginx-debug', '-g', 'daemon off;']
                },
                'chrome_beta': {
                    'container_name': 'chrome_beta',
                    'image': 'nginx',
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'insights-chrome')}:/usr/share/nginx/html"],
                    'command': ['nginx-debug', '-g', 'daemon off;']
                },
                'landing': {
                    'container_name': 'landing',
                    'image': 'nginx',
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'landing-page-frontend', 'dist')}:/usr/share/nginx/html/apps/landing"],
                    'command': ['nginx-debug', '-g', 'daemon off;']
                },
                'landing_beta': {
                    'container_name': 'landing_beta',
                    'image': 'nginx',
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'landing-page-frontend', 'dist')}:/usr/share/nginx/html/beta/apps/landing"],
                    'command': ['nginx-debug', '-g', 'daemon off;']
                },
                'entitlements': {
                    'container_name': 'entitlements',
                    'image': 'python:3',
                    'build': {
                        'context': f"{os.path.join(self.checkouts_root, 'entitlements')}",
                    },
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'entitlements')}:/app"]
                },
                'rbac': {
                    'container_name': 'rbac',
                    'image': 'python:3',
                    'build': {
                        'context': f"{os.path.join(self.checkouts_root, 'rbac')}",
                    },
                    'volumes': [f"./{os.path.join(self.checkouts_root, 'rbac')}:/app"]
                }

            }
        }

        yaml = YAML(typ='rt', pure=True)
        yaml.preserve_quotes = True
        yaml.indent=4
        yaml.block_seq_indent=4
        yaml.explicit_start = True
        yaml.width = 1000
        yaml.default_flow_style = False

        #pprint(ds)

        with open('genstack.yml', 'w') as f:
            yaml.dump(ds, f)


    def get_npm_path(self):
        # /home/vagrant/.nvm/versions/node/v10.15.3/bin/npm
        npath = os.path.expanduser('~/.nvm/versions/node/v10.15.3/bin/npm')
        return npath

    def make_spandx(self):
        stemp = SPANDX_TEMPLATE
        stemp = stemp.replace("FRONTEND", self.frontend)
        stemp = stemp.replace("BACKEND", self.backend)
        with open(os.path.join(self.webroot, 'spandx.config.js'), 'w') as f:
            f.write(stemp)

    def make_www(self):
        apps_path = os.path.join(self.webroot, 'apps')
        chrome_src = os.path.join(self.checkouts_root, 'insights-chrome')

        if not os.path.exists(apps_path):
            os.makedirs(apps_path)

        '''
        # apps/chrome should point at the chrome build path
        if not os.path.exists(os.path.join(apps_path, 'chrome')):
            cmd = f'ln -s ../../{chrome_src} chrome'
            print(cmd)
            subprocess.run(cmd, cwd=apps_path, shell=True)
        '''

        # get index.html and make it point at the right chrome css file ...
        if not os.path.exists(os.path.join(self.webroot, 'index.html')):
            cmd = 'curl -o index.html https://cloud.redhat.com'
            subprocess.run(cmd, cwd=self.webroot, shell=True)
            cmd = 'sed -i.bak "s/chrome\..*\.css/chrome\.css/" index.html && rm -f index.html.bak'
            subprocess.run(cmd, cwd=self.webroot, shell=True)

        # symlink the silent-check-sso.html
        ssof = os.path.join(self.checkouts_root, 'landing-page-frontend', 'dist', 'silent-check-sso.html')
        dst = os.path.join(self.webroot, 'silent-check-sso.html')
        if not os.path.exists(dst):
            os.link(ssof, dst)

    def make_landing(self):
        # clone it
        repo = 'https://github.com/RedHatInsights/landing-page-frontend'
        srcpath = os.path.join(self.checkouts_root, 'landing-page-frontend')

        if not os.path.exists(srcpath):
            if os.path.exists(srcpath):
                shutil.rmtree(srcpath)
            cmd = f'git clone {repo} {srcpath}'
            cmd = cmd.split()
            print(cmd)
            subprocess.run(cmd)

        nm = os.path.join(srcpath, 'node_modules')
        if not os.path.exists(nm):
            cmd = f'{self.get_npm_path()} install'
            print(cmd)
            subprocess.run(cmd, cwd=srcpath, shell=True)

        if not os.path.exists(os.path.join(srcpath, 'dist')):
            cmd = f'{self.get_npm_path()} run build'
            print(cmd)
            subprocess.run(cmd, cwd=srcpath, shell=True)

    def make_chrome(self, build=False):

        # clone it
        repo = 'https://github.com/RedHatInsights/insights-chrome'
        srcpath = os.path.join(self.checkouts_root, 'insights-chrome')

        if not os.path.exists(srcpath):
            if os.path.exists(srcpath):
                shutil.rmtree(srcpath)
            cmd = f'git clone {repo} {srcpath}'
            cmd = cmd.split()
            print(cmd)
            subprocess.run(cmd)

        self.set_chrome_jwt_constants()

        '''
        # install pkgs from cache or from npm
        nm = os.path.join(self.cache_root, 'chrome_node_modules')
        if not os.path.exists(nm):
            cmd = ['npm', 'install']
            print(cmd)
            subprocess.run(cmd, cwd=srcpath)
            shutil.copytree(os.path.join(srcpath, 'node_modules'), nm)
        else:
            print(f'cp -Rp {nm} -> {srcpath}/node_modules')
            #shutil.copytree(nm, os.path.join(srcpath, 'node_modules'))
            subprocess.run(['cp', '-Rp', os.path.abspath(nm), 'node_modules'], cwd=srcpath)
            #print(f'ln -s {nm} {srcpath}/node_modules')
            #subprocess.run(['ln', '-s', os.path.abspath(nm), 'node_modules'], cwd=srcpath)
        '''
        nm = os.path.join(srcpath, 'node_modules')
        if not os.path.exists(nm):
            cmd = [self.get_npm_path(), 'install']
            print(cmd)
            subprocess.run(cmd, cwd=srcpath)

        # build the src
        if os.path.exists(os.path.join(srcpath, 'build')) and build:
            shutil.rmtree(os.path.join(srcpath, 'build'))
        if not os.path.exists(os.path.join(srcpath, 'build')):
            subprocess.run([self.get_npm_path(), 'run', 'build'], cwd=srcpath)

        # node_modules -must- be served from the build root
        if not os.path.exists(os.path.join(srcpath, 'build', 'node_modules')):
            cmd = 'ln -s ../node_modules node_modules'
            subprocess.run(cmd, cwd=os.path.join(srcpath, 'build'), shell=True)

        # make a shim for /apps/chrome to build
        apps = os.path.join(srcpath, 'apps')
        if not os.path.exists(apps):
            os.makedirs(apps)
        if not os.path.exists(os.path.join(apps, 'chrome')):
            cmd = 'ln -s ../build chrome'
            subprocess.run(cmd, cwd=apps, shell=True)

        bpath = os.path.join(srcpath, 'beta')
        if not os.path.exists(bpath):
            os.makedirs(bpath)
        if not os.path.exists(os.path.join(bpath, 'apps')):
            cmd = 'ln -s ../apps apps'
            subprocess.run(cmd, cwd=bpath, shell=True)



    def set_chrome_jwt_constants(self):
        # src/insights-chrome/src/js/jwt/constants.js
        srcpath = os.path.join(self.checkouts_root, 'insights-chrome')
        constants_path = os.path.join(srcpath, 'src', 'js', 'jwt', 'constants.js')
        with open(constants_path, 'r') as f:
            cdata = f.read()

        cdata = cdata.replace('https://sso.redhat.com', self.keycloak)

        with open(constants_path, 'w') as f:
            f.write(cdata)

    def fix_chrome(self):
        srcpath = os.path.join(self.checkouts_root, 'insights-chrome')

        # link the hashed css file to non-hashed
        if os.path.exists(os.path.join(srcpath, 'build', 'chrome.css')):
            os.remove(os.path.join(srcpath, 'build', 'chrome.css'))
        cmd = 'ln -s chrome.*.css chrome.css'
        subprocess.run(cmd, cwd=os.path.join(srcpath, 'build'), shell=True)

        # link the hashed js file to non-hashed
        if os.path.exists(os.path.join(srcpath, 'build', 'js', 'chrome.js')):
            os.remove(os.path.join(srcpath, 'build', 'js', 'chrome.js'))
        cmd = 'ln -s chrome.*.js chrome.js'
        subprocess.run(cmd, cwd=os.path.join(srcpath, 'build', 'js'), shell=True)

    def make_rbac(self):
        srcpath = os.path.join(self.checkouts_root, 'rbac')
        if os.path.exists(srcpath):
            shutil.rmtree(srcpath)
        os.makedirs(srcpath)

        with open(os.path.join(srcpath, 'api.py'), 'w') as f:
            f.write(ENTITLEMENTS_SERVER)
        with open(os.path.join(srcpath, 'Dockerfile'), 'w') as f:
            f.write(FLASKDOCKERFILE)
        with open(os.path.join(srcpath, 'requirements.txt'), 'w') as f:
            f.write(FLASKREQUIREMENTS)

    def make_entitlements(self):
        srcpath = os.path.join(self.checkouts_root, 'entitlements')
        if os.path.exists(srcpath):
            shutil.rmtree(srcpath)
        os.makedirs(srcpath)

        with open(os.path.join(srcpath, 'api.py'), 'w') as f:
            f.write(ENTITLEMENTS_SERVER)
        with open(os.path.join(srcpath, 'Dockerfile'), 'w') as f:
            f.write(FLASKDOCKERFILE)
        with open(os.path.join(srcpath, 'requirements.txt'), 'w') as f:
            f.write(FLASKREQUIREMENTS)


def main():
    cbuilder = CloudBuilder()
    #cbuilder.set_chrome_jwt_constants()
    cbuilder.make_chrome(build=True)
    cbuilder.fix_chrome()
    cbuilder.make_www()
    cbuilder.make_landing()
    cbuilder.make_entitlements()
    cbuilder.make_rbac()

    cbuilder.make_spandx()
    cbuilder.create_compose_file()


if __name__ == "__main__":
    main()
