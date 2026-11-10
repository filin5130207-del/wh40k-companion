# ODPM notes

This repository ships an `odpm.json` for **Odoo 20.0** so teams can use [ODPM](https://github.com/aayartsev/odpm) as the package/module workflow.

```json
{
  "odpm_version": "4.0",
  "odoo_version": "20.0",
  "python_version": "3.14",
  "distro_name": "debian",
  "distro_version": "13",
  "postgres_version": "18",
  "odoo_git_link": "https://github.com/odoo/odoo.git",
  "platform_name": "odoo"
}
```

Typical flow once Docker is available on the host:

```bash
pip install odpm
odpm plan
odpm -d wh40k -i wh40k_companion
odpm -d wh40k -u wh40k_companion
```

For a lighter path without generating the full ODPM workspace, use the committed `docker-compose.yml` (official `odoo:20.0` image + Postgres) described in the root README.
