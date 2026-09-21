-- Manual-entry queue: sites the crawler cannot enter (WAF 403, robots disallow).
-- One row per blocked domain, enriched with whatever the discovery sources
-- already know, so a human can verify details and enter contacts in Retool.
-- Per D-003, blocked sites are never fought around - they route here.

create or replace view manual_entry_queue as
with blocked as (
  select domain,
         min(url)                          as url,
         min(fail_reason)                  as fail_reason,
         min(finished_at)                  as last_attempt_at
  from crawl_jobs
  where status = 'failed' and fail_category = 'blocked'
  group by domain
)
select b.domain,
       b.url,
       b.fail_reason,
       b.last_attempt_at,
       o.id                as org_id,
       coalesce(o.name, c.name)        as name,
       o.email             as org_email,
       o.phone             as org_phone,
       c.email             as candidate_email,
       c.phone             as candidate_phone,
       coalesce(o.address_line1, c.address_line1) as address_line1,
       coalesce(o.city, c.city)        as city,
       coalesce(o.province, c.province) as province,
       c.source_id         as candidate_source
from blocked b
left join organizations o
  on o.website is not null
 and lower(regexp_replace(o.website, '^https?://(www\.)?', '', 'i'))
     like '%' || b.domain || '%'
left join lateral (
  select oc.name, oc.email, oc.phone, oc.address_line1, oc.city, oc.province, oc.source_id
  from org_candidates oc
  where oc.website is not null
    and lower(regexp_replace(oc.website, '^https?://(www\.)?', '', 'i'))
        like '%' || b.domain || '%'
  order by oc.created_at
  limit 1
) c on true
order by b.domain;
