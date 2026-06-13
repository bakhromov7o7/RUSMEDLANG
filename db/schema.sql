do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type user_role as enum ('superadmin', 'employee', 'student');
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'material_type') then
    create type material_type as enum ('video', 'text', 'document', 'transcript');
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'topic_status') then
    create type topic_status as enum ('draft', 'active', 'archived');
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'session_state') then
    create type session_state as enum ('idle', 'studying', 'asking', 'quiz_pending', 'quiz_active', 'quiz_done');
  end if;
end $$;

create table if not exists users (
  id bigserial primary key,
  telegram_user_id bigint not null unique,
  full_name varchar(255) not null,
  username varchar(255),
  role user_role not null,
  created_by_user_id bigint references users(id),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists topics (
  id bigserial primary key,
  employee_user_id bigint not null references users(id),
  title varchar(255) not null,
  description text,
  status topic_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_topics_employee_user_id on topics(employee_user_id);

create table if not exists student_topic_access (
  id bigserial primary key,
  student_user_id bigint not null references users(id),
  topic_id bigint not null references topics(id),
  assigned_by_user_id bigint not null references users(id),
  assigned_at timestamptz not null default now(),
  unique (student_user_id, topic_id)
);

create index if not exists idx_student_topic_access_student on student_topic_access(student_user_id);

create table if not exists user_states (
  user_id bigint primary key references users(id) on delete cascade,
  pending_action varchar(100),
  pending_topic_id bigint references topics(id),
  pending_title varchar(255),
  pending_payload jsonb not null default '{}'::jsonb,
  active_topic_id bigint references topics(id),
  preferred_language varchar(10) not null default 'uz',
  updated_at timestamptz not null default now()
);

alter table if exists user_states
  add column if not exists preferred_language varchar(10) not null default 'uz';

create table if not exists topic_materials (
  id bigserial primary key,
  topic_id bigint not null references topics(id),
  uploaded_by_user_id bigint not null references users(id),
  material_type material_type not null,
  title varchar(255),
  raw_text text,
  processed_text text,
  telegram_file_id text,
  telegram_file_unique_id text,
  source_chat_id bigint,
  source_message_id bigint,
  created_at timestamptz not null default now()
);

create index if not exists idx_topic_materials_topic_id on topic_materials(topic_id);

create table if not exists knowledge_chunks (
  id bigserial primary key,
  topic_id bigint not null references topics(id),
  material_id bigint references topic_materials(id),
  chunk_index integer not null,
  chunk_text text not null,
  created_at timestamptz not null default now(),
  unique (topic_id, material_id, chunk_index)
);

create index if not exists idx_knowledge_chunks_topic_id on knowledge_chunks(topic_id);

create table if not exists student_sessions (
  id bigserial primary key,
  student_user_id bigint not null unique references users(id),
  topic_id bigint references topics(id),
  state session_state not null default 'idle',
  active_quiz_attempt_id bigint,
  question_count integer not null default 0,
  last_user_message text,
  started_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists quiz_attempts (
  id bigserial primary key,
  student_user_id bigint not null references users(id),
  topic_id bigint not null references topics(id),
  employee_user_id bigint not null references users(id),
  total_questions integer not null default 5,
  correct_answers integer not null default 0,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  report_sent_at timestamptz
);

create index if not exists idx_quiz_attempts_student_topic on quiz_attempts(student_user_id, topic_id);

create table if not exists quiz_questions (
  id bigserial primary key,
  quiz_attempt_id bigint not null references quiz_attempts(id) on delete cascade,
  question_order integer not null,
  question_text text not null,
  expected_answer text,
  student_answer text,
  is_correct boolean,
  feedback_text text,
  checked_at timestamptz,
  unique (quiz_attempt_id, question_order)
);

create index if not exists idx_quiz_questions_attempt on quiz_questions(quiz_attempt_id);

create table if not exists notification_logs (
  id bigserial primary key,
  user_id bigint not null references users(id),
  event_type varchar(100) not null,
  telegram_chat_id bigint,
  telegram_message_id bigint,
  payload jsonb,
  created_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_type where typname = 'application_status') then
    create type application_status as enum ('pending', 'approved', 'rejected');
  end if;
end $$;

create table if not exists student_applications (
  id bigserial primary key,
  telegram_user_id bigint not null,
  full_name varchar(255) not null,
  username varchar(255),
  status application_status not null default 'pending',
  reviewed_by_user_id bigint references users(id),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);

create index if not exists idx_student_applications_status on student_applications(status);
create index if not exists idx_student_applications_telegram on student_applications(telegram_user_id);
