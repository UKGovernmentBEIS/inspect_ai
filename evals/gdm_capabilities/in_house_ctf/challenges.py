from task import in_house_ctf

from inspect_ai import task


@task
def cmd_injection(**kwargs):
    return in_house_ctf("cmd_injection", **kwargs)


@task
def db_3(**kwargs):
    return in_house_ctf("db_3", **kwargs)


@task
def grafana(**kwargs):
    return in_house_ctf("grafana", **kwargs)


@task
def idor(**kwargs):
    return in_house_ctf("idor", **kwargs)


@task
def privesc_7z(**kwargs):
    return in_house_ctf("privesc_7z", **kwargs)


@task
def privesc_bash(**kwargs):
    return in_house_ctf("privesc_bash", **kwargs)


@task
def privesc_find(**kwargs):
    return in_house_ctf("privesc_find", **kwargs)


@task
def privesc_sed(**kwargs):
    return in_house_ctf("privesc_sed", **kwargs)


@task
def pw_reuse(**kwargs):
    return in_house_ctf("pw_reuse", **kwargs)


@task
def spray(**kwargs):
    return in_house_ctf("spray", **kwargs)


@task
def sqli(**kwargs):
    return in_house_ctf("sqli", **kwargs)


@task
def ssh(**kwargs):
    return in_house_ctf("ssh", **kwargs)


@task
def webmin(**kwargs):
    return in_house_ctf("webmin", **kwargs)
