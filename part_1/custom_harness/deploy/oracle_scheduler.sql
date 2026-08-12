-- Run as the ERPA application owner for an externally provisioned database.
-- Compose installs the same idempotent queue + job from bootstrap_oracle.py.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE erpa_brief_queue (
      request_id VARCHAR2(64) PRIMARY KEY,
      user_id VARCHAR2(32) NOT NULL,
      prompt VARCHAR2(200) NOT NULL,
      status VARCHAR2(16) DEFAULT 'queued' NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      completed_at TIMESTAMP,
      error_message VARCHAR2(2000)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

DECLARE
  job_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO job_count
  FROM user_scheduler_jobs
  WHERE job_name = 'ERPA_MORNING_BRIEF_JOB';

  IF job_count = 0 THEN
    DBMS_SCHEDULER.CREATE_JOB(
      job_name        => 'ERPA_MORNING_BRIEF_JOB',
      job_type        => 'PLSQL_BLOCK',
      job_action      => q'[BEGIN
        INSERT INTO erpa_brief_queue(request_id,user_id,prompt)
        VALUES (RAWTOHEX(SYS_GUID()), 'planner-01', 'Morning brief.');
        COMMIT;
      END;]',
      start_date      => SYSTIMESTAMP,
      repeat_interval => 'FREQ=WEEKLY;BYDAY=MON,TUE,WED,THU,FRI;BYHOUR=8;BYMINUTE=0;BYSECOND=0',
      enabled         => TRUE,
      comments        => 'Queues ERPA input; the worker runs the standard OracleSaver-backed graph.'
    );
  END IF;
END;
/

SELECT job_name, enabled, state, next_run_date
FROM user_scheduler_jobs
WHERE job_name = 'ERPA_MORNING_BRIEF_JOB';
