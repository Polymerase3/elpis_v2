-- 001-init.sql for PostgreSQL

-- 1) Create helper schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS helper;

-- 2) Grant all privileges on that schema to the polymerase user
GRANT ALL PRIVILEGES ON SCHEMA helper TO polymerase;

-- 3) Define a reusable function to create arbitrary DBs
DROP FUNCTION IF EXISTS create_db_if_not_exists(text);

CREATE OR REPLACE FUNCTION create_db_if_not_exists(dbname TEXT)
  RETURNS VOID
  LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM   pg_database
    WHERE  datname = dbname
  ) THEN
    EXECUTE format('CREATE DATABASE %I OWNER polymerase', dbname);
  END IF;
END;
$$;

-- 4) Ensure the "elpis" database exists, and grant privileges
--    This runs as the superuser in init, so will create the DB if needed
SELECT create_db_if_not_exists('elpis');

-- Grant full access on the newly-created database to polymerase
GRANT ALL PRIVILEGES ON DATABASE elpis TO polymerase;

-- 5) (Optional) If you want helper objects inside elpis, you can reconnect and set up there:
\connect elpis

-- Done.
