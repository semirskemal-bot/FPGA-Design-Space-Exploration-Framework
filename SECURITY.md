# Security

## Command execution boundary

The shell adapter intentionally executes commands from a local study configuration. Treat `dse.yml` files like scripts: review configurations from untrusted sources before running them. The restricted expression evaluator does not permit attributes, indexing, imports, lambdas, or Python builtins, but that restriction does not sandbox the shell adapter.

## Sensitive artifacts

Vendor logs and reports can contain source paths, device identifiers, user names, license-server details, or proprietary design information. The default `.gitignore` excludes common generated FPGA artifacts and the complete `.dse` workspace. Review files before publishing a report.

## Reporting a vulnerability

Open a private GitHub security advisory for vulnerabilities. Do not include secrets, proprietary RTL, or license credentials in public issues.
