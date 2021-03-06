#!/usr/bin/env python
from __future__ import print_function
from requests import get
from requests.exceptions import RequestException
import yaml, time, os
from datetime import datetime
from sys import exit
from smtplib import SMTP

def timestamp(s):
  return datetime.strptime(s[0:19], "%Y-%m-%dT%H:%M:%S")

def notify(notif, to, **keys):
  if not to:
    print("%s:%s: cannot send notification: no email contact" % (keys["repo"], keys["stratum_name"]))
    return
  subject = notif["subject"] % keys
  body = "Subject: %s\nFrom: %s\nTo: %s\n\n" % (subject, notif["from"], ", ".join(to))
  body += notif["body"] % keys
  if os.environ.get("CVMFSMON_NO_NOTIF", "0") != "0":
    print("%(repo)s:%(stratum_name)s: would send the following email through " \
          "%(host)s:%(port)d:\n---\n%(body)s\n---" %  { "repo": keys["repo"],
                                                        "stratum_name": keys["stratum_name"],
                                                        "host": notif["smtp"]["host"],
                                                        "port": notif["smtp"]["port"],
                                                        "body": body })
    return
  try:
    mailer = SMTP(notif["smtp"]["host"], notif["smtp"]["port"])
    mailer.sendmail(notif["from"], to, body)
  except Exception as e:
    print("%s:%s: cannot send email: %s:%s" % (keys["repo"], keys["stratum_name"], type(e), e))
    return
  print("%s:%s: notification sent to %s" % (keys["repo"], keys["stratum_name"], ", ".join(to)))

def getint(d, key, default):
  v = d.get(key, default)
  try:
    return int(v)
  except ValueError:
    return default

def check(monit):
  for repo in monit["repos"]:
    for stratum_name in monit["repos"][repo]:
      try:
        s = get(monit["repos"][repo][stratum_name]["url"]).json()
        pub_delta = (datetime.utcnow()-timestamp(s["stratum0"]["last_modified"])).total_seconds()
        revdiff = s["stratum0"]["revision"]-s["stratum1"]["revision"]
        ok = s["status"] == "ok"
      except (RequestException,KeyError,ValueError) as e:
        print("%s:%s: cannot get monitoring info: %s:%s" % (repo, stratum_name, type(e), e))
        continue

      if revdiff == 0:
        print("%s:%s: OK" % (repo, stratum_name))
      elif revdiff <= monit["max_revdelta"] and pub_delta <= monit["max_timedelta"]:
        print("%s:%s: syncing: %d seconds, %d revisions behind (stratum0 updated %d seconds ago)" % \
          (repo, stratum_name, pub_delta, revdiff, pub_delta))
      else:
        print("%s:%s: error: %d seconds, %d revisions behind (stratum0 updated %d seconds ago)" % \
          (repo, stratum_name, pub_delta, revdiff, pub_delta))
        if time.time()-monit["repos"][repo][stratum_name].get("last_notification", 0) > monit["snooze"]:
          notify(monit["notif"],
                 to=monit["repos"][repo][stratum_name]["contact"],
                 stratum_name=stratum_name,
                 repo=repo,
                 api_url=monit["repos"][repo][stratum_name]["url"],
                 delta_rev=revdiff,
                 delta_time=pub_delta,
                 stratum0_mod=s["stratum0"]["last_modified"],
                 stratum1_mod=s["stratum1"]["last_modified"],
                 stratum0_rev=s["stratum0"]["revision"],
                 stratum1_rev=s["stratum1"]["revision"])
          monit["repos"][repo][stratum_name]["last_notification"] = time.time()

if __name__ == "__main__":
  try:
    monit = yaml.safe_load(open("cvmfs-mon.yml"))
    for repo in monit["repos"]:
      for stratum_name in monit["repos"][repo]:
        monit["repos"][repo][stratum_name]["url"]
        if "contact" in monit["repos"][repo][stratum_name]:
          monit["repos"][repo][stratum_name]["contact"] = monit["repos"][repo][stratum_name]["contact"].split(",")
        else:
          monit["repos"][repo][stratum_name]["contact"] = None
  except (yaml.YAMLError,IOError,KeyError) as e:
    print("cannot parse configuration: %s:%s" % (type(e), e))
    exit(1)

  monit["notif"] = monit.get("notif", {})
  for k in ["from", "subject", "body", "smtp"]:
    if not k in monit["notif"]:
      monit["notif"] = {}
  if monit["notif"]:
    monit["notif"]["smtp"] = monit["notif"]["smtp"].split(":", 1)
    try:
      monit["notif"]["smtp"].append(int(monit["notif"]["smtp"].pop(1)))
    except (ValueError,IndexError) as e:
       monit["notif"]["smtp"].append(25) # default smtp port
    monit["notif"]["smtp"] = dict(zip(["host", "port"], monit["notif"]["smtp"]))
    print("email notifications will be sent via %(host)s:%(port)d" % monit["notif"]["smtp"])
  else:
    print("email notifications disabled")
    notify = lambda *x, **y: False

  monit["sleep"] = getint(monit, "sleep", 120)
  monit["snooze"] = getint(monit, "snooze", 3600)
  monit["max_timedelta"] = getint(monit, "max_timedelta", 7200)
  monit["max_revdelta"] = getint(monit, "max_revdelta", 7200)

  while True:
    check(monit)
    print("sleeping %d seconds" % monit["sleep"])
    time.sleep(monit["sleep"])
