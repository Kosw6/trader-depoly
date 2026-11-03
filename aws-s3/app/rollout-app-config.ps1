param(
    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$Bucket,

    [Parameter(Mandatory = $true)]
    [string]$FrontendOrigin,

    [Parameter(Mandatory = $true)]
    [string[]]$InstanceIds
)

$ErrorActionPreference = "Stop"

$commands = @(
    "set -eu",
    "cd /data/app",
    "aws s3 cp s3://$Bucket/app/docker-compose.yml docker-compose.yml",
    "aws s3 cp s3://$Bucket/app/.env.template .env.template",
    "if grep -q '^CORS_ALLOWED_ORIGINS=' .env; then sed -i 's|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=$FrontendOrigin,http://localhost:*|' .env; else printf '\nCORS_ALLOWED_ORIGINS=$FrontendOrigin,http://localhost:*\n' >> .env; fi",
    "docker compose up -d --force-recreate app",
    "for i in `$(seq 1 60); do curl -fsS http://localhost:8080/actuator/health >/dev/null && exit 0; sleep 5; done",
    "docker compose logs --tail=100 app",
    "exit 1"
)

$payload = @{
    DocumentName = "AWS-RunShellScript"
    InstanceIds  = $InstanceIds
    Parameters   = @{
        commands = $commands
    }
} | ConvertTo-Json -Depth 6

$payloadPath = Join-Path $env:TEMP "trader-app-rollout-$([guid]::NewGuid().ToString('N')).json"

try {
    [System.IO.File]::WriteAllText(
        $payloadPath,
        $payload,
        [System.Text.UTF8Encoding]::new($false)
    )

    $commandId = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $commandId = & aws ssm send-command `
            --region $Region `
            --cli-input-json "file://$payloadPath" `
            --query "Command.CommandId" `
            --output text 2>$null

        if ($LASTEXITCODE -eq 0 -and $commandId) {
            break
        }

        if ($attempt -eq 60) {
            throw "App instances did not become available through SSM."
        }

        Start-Sleep -Seconds 10
    }

    foreach ($instanceId in $InstanceIds) {
        & aws ssm wait command-executed `
            --region $Region `
            --command-id $commandId `
            --instance-id $instanceId

        if ($LASTEXITCODE -ne 0) {
            throw "Timed out waiting for app rollout on $instanceId."
        }

        $status = & aws ssm get-command-invocation `
            --region $Region `
            --command-id $commandId `
            --instance-id $instanceId `
            --query "Status" `
            --output text

        if ($LASTEXITCODE -ne 0 -or $status -ne "Success") {
            $details = & aws ssm get-command-invocation `
                --region $Region `
                --command-id $commandId `
                --instance-id $instanceId `
                --query "{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}" `
                --output json
            throw "App rollout failed on $instanceId. $details"
        }
    }
}
finally {
    if (Test-Path -LiteralPath $payloadPath) {
        Remove-Item -LiteralPath $payloadPath -Force
    }
}
