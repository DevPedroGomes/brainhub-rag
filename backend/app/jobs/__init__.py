"""Trabalho que roda FORA do processo que atende HTTP.

Por que existe: se a ingestao rodasse em `BackgroundTasks`, ou seja, no proprio
processo do uvicorn, depois da resposta, um redeploy no meio de uma ingestao
longa perderia o trabalho em silencio, e uma operacao bloqueante travaria ate o
`/healthz`. Tudo que mora aqui e chamado por um worker separado.
"""
