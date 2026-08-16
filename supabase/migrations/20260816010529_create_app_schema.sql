create schema if not exists app;

-- FastAPI se conecta con una llave secreta, que usa el rol service_role.
-- Ese rol salta RLS, así que no hace falta concederle nada explícito.
-- Los roles de la Data API no deben poder ni ver el esquema.
revoke all on schema app from anon, authenticated;
