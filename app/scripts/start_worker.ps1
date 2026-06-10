$CONCURRENCY = if ($env:CONCURRENCY) { $env:CONCURRENCY } else { 2 }
$LOG_LEVEL   = if ($env:LOG_LEVEL) { $env:LOG_LEVEL } else { "info" }
$QUEUE       = if ($env:QUEUE) { $env:QUEUE } else { "resume_processing" }

Write-Host "Starting HireMatch Celery worker..."
Write-Host "Queue      : $QUEUE"
Write-Host "Concurrency: $CONCURRENCY"
Write-Host "Log level  : $LOG_LEVEL"

celery -A app.celery.celery_app:celery_app worker `
    --queues=$QUEUE `
    --concurrency=$CONCURRENCY `
    --loglevel=$LOG_LEVEL `
    --hostname="hirematch-worker@%h"