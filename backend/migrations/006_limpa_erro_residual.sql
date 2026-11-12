-- 006: apaga a causa de falha que ficou grudada em documento que deu certo.
--
-- MOTIVACAO: um UPDATE de sucesso da ingestao que grava status='completed' sem
-- tocar em `meta` deixa um documento que falhou, foi reprocessado e completou
-- carregando o erro da tentativa anterior.
--
-- Como a API projeta a causa, o residuo viraria erro exibido em documento que
-- funciona.
--
-- O conserto da origem esta em jobs/ingestao.py, no mesmo UPDATE de sucesso:
-- `meta = COALESCE(meta,'{}'::jsonb) - 'error'`. Esta migration so limpa o que
-- ficou para tras.

UPDATE documents
   SET meta = COALESCE(meta, '{}'::jsonb) - 'error'
 WHERE status = 'completed'
   AND meta ? 'error';
