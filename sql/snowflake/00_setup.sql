-- One-time setup on a real Snowflake account (run as ACCOUNTADMIN).
-- Creates a small, auto-suspending warehouse and a least-privilege role.

create warehouse if not exists SPEND_COPILOT_WH
  warehouse_size = 'XSMALL' auto_suspend = 60 auto_resume = true initially_suspended = true;

create database if not exists SPEND_COPILOT;
create schema if not exists SPEND_COPILOT.RAW;

create role if not exists SPEND_COPILOT_ROLE;
grant usage on warehouse SPEND_COPILOT_WH to role SPEND_COPILOT_ROLE;
grant all on database SPEND_COPILOT to role SPEND_COPILOT_ROLE;
grant all on all schemas in database SPEND_COPILOT to role SPEND_COPILOT_ROLE;
grant all on future schemas in database SPEND_COPILOT to role SPEND_COPILOT_ROLE;

-- Read access to usage views (ACCOUNT_USAGE) without full ACCOUNTADMIN
grant database role SNOWFLAKE.USAGE_VIEWER to role SPEND_COPILOT_ROLE;

grant role SPEND_COPILOT_ROLE to user identifier($MY_USER);  -- set MY_USER first: set MY_USER = 'YOUR_USER';
