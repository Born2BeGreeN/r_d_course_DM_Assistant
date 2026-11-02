"""Submission regressions using isolated Git repositories; no commits or model calls."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def git(tmp_path,*args):
    return subprocess.run(['git','-C',str(tmp_path),*args],capture_output=True,check=True).stdout


@pytest.fixture
def checkout(tmp_path):
    if not shutil.which('git'):
        pytest.skip('Git not installed')
    git(tmp_path,'init','-q')
    git(tmp_path,'config','core.autocrlf','true')
    for name in ('.gitattributes','.gitignore'):
        shutil.copyfile(ROOT/name,tmp_path/name)
    return tmp_path


def test_frozen_bytes_survive_git_clean_filter_on_windows(checkout):
    for name,payload in [('prompt.txt',b'one\r\ntwo\r\n'),('schema.py',b'one\ntwo\n'),('labels.json',b'{"synthetic":true}\n')]:
        (checkout/name).write_bytes(payload)
        assert git(checkout,'hash-object','--path='+name,name)==git(checkout,'hash-object','--no-filters',name)


def test_secrets_ignored_but_review_artifacts_trackable(checkout):
    for path in ('.env','.env.local','secret.env','.venv/cache','data/raw/source.pdf','data/extracted/candidate.txt','data/ocr/page.txt'):
        assert git(checkout,'check-ignore','--no-index',path).strip()
    for path in ('.env.example','data/texts/input.txt','data/golden/input.json','results/run.json','prompts/v2.txt'):
        result=subprocess.run(['git','-C',str(checkout),'check-ignore','--no-index',path],capture_output=True)
        assert result.returncode==1
