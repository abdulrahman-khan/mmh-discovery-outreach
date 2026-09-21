-- Staff directory view: one row per organization with contact rollups,
-- suppression flags, and the outreach-readiness score computed in SQL.
-- Scoring is the export_readiness.py formula (D-020: score is internal).
-- Suppressed contacts never appear in the rollups: suppression is absolute
-- (kind email/phone/domain/org), so a suppressed value is invisible here -
-- any list or export built on this view cannot surface it.

create or replace function org_readiness_score(o organizations, has_email boolean,
    has_phone boolean, has_form boolean, email_methods text,
    email_from_contact boolean) returns int
language sql stable as $$
  select least(100,
    -- primary channel (capped) + breadth
    (case when has_email or has_phone or has_form
          then least(45, (case when has_email then 45 else 0 end)
                            + (case when has_phone then 25 else 0 end)
                            + (case when has_form  then 20 else 0 end))
          else 0 end)
    + (case when (has_email::int + has_phone::int + has_form::int) >= 2
            then 10 else 0 end)
    -- social presence (max 10)
    + least(5 * (select count(*) from jsonb_object_keys(o.social)), 10)
    -- mail-merge completeness
    + (case when coalesce(o.city, '') <> '' then 10 else 0 end)
    + (case when coalesce(o.postal_code, '') <> '' then 10 else 0 end)
    -- evidence quality
    + (case when o.email is null then 0
            when email_methods like '%v2%' then 10 else 5 end)
    + (case when o.email is not null and email_from_contact then 10 else 0 end)
    -- org-domain email (not a free inbox); regexp 'i' only matches, it does not
    -- lowercase - the host must be lower()ed explicitly
    + (case when o.email is not null and o.website is not null
              and (lower(split_part(regexp_replace(o.website, '^https?://(www\.)?', '', 'i'), '/', 1)) = lower(split_part(o.email, '@', 2))
                   or lower(split_part(regexp_replace(o.website, '^https?://(www\.)?', '', 'i'), '/', 1)) like '%.' || lower(split_part(o.email, '@', 2))
                   or lower(split_part(o.email, '@', 2)) like '%.' || lower(split_part(regexp_replace(o.website, '^https?://(www\.)?', '', 'i'), '/', 1)))
            then 5 else 0 end));
$$;

create or replace view directory_view as
with sup as (  -- suppressed values, one pass
  select
    array(select lower(value) from suppression where kind = 'email')       as emails,
    array(select lower(regexp_replace(value, '\D', '', 'g'))
          from suppression where kind = 'phone')                    as phones
),
live_contacts as (  -- contacts minus anything suppressed
  select c.org_id, c.kind, c.value, c.id
  from contacts c, sup
  where c.invalid = false
    and not (c.kind = 'email' and lower(c.value) = any (sup.emails))
    and not (c.kind = 'phone' and sup.phones <> '{}'
             and regexp_replace(c.value, '\D', '', 'g') = any (sup.phones))
),
rollup as (
  select org_id,
         bool_or(kind = 'email')        as has_email,
         bool_or(kind = 'phone')        as has_phone,
         bool_or(kind = 'contact_form') as has_form,
         count(distinct kind)           as n_channels
  from live_contacts
  group by org_id
),
email_prov as (
  select c.org_id,
         coalesce(string_agg(distinct fp.method, ','), '')          as methods,
         coalesce(bool_or(sr.url ilike '%contact%'), false)         as from_contact
  from contacts c
  join field_provenance fp on fp.entity_type = 'contact'
                          and fp.field = 'email' and fp.entity_id = c.id
  left join source_records sr on sr.id = fp.source_record_id
  where c.kind = 'email'
  group by c.org_id
)
select o.id, o.name, o.status, o.website,
       o.address_line1, o.city,
       upper(o.province) as province, o.postal_code, o.lat, o.lng,
       o.social, o.confidence, o.verified_at, o.notes,
       -- primary contacts nulled when their value is suppressed
       (case when lower(o.email) = any (s.emails) then null else o.email end) as email,
       (case when o.phone is not null and s.phones <> '{}'
              and regexp_replace(o.phone, '\D', '', 'g') = any (s.phones)
             then null else o.phone end)  as phone,
       coalesce(r.has_email, false)  as has_email,
       coalesce(r.has_phone, false)  as has_phone,
       coalesce(r.has_form, false)   as has_form,
       coalesce(r.n_channels, 0)     as n_channels,
       org_readiness_score(o, coalesce(r.has_email, false),
              coalesce(r.has_phone, false), coalesce(r.has_form, false),
              coalesce(ep.methods, ''), coalesce(ep.from_contact, false)) as score,
       (exists (select 1 from suppression
                where kind = 'org' and lower(value) = o.id::text)) as org_suppressed,
       (o.website is not null and exists
          (select 1 from suppression s2
           where s2.kind = 'domain'
             and position(s2.value in lower(o.website)) > 0))      as domain_suppressed,
       exists (select 1 from field_provenance fp
               where fp.entity_type = 'org' and fp.entity_id = o.id
                 and fp.method = 'manual')                         as has_manual_edits
from organizations o
cross join sup s
left join rollup r     on r.org_id = o.id
left join email_prov ep on ep.org_id = o.id
where o.status <> 'merged' and o.merged_into is null;
