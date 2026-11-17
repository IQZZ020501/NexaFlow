"""Atomic Run resource bundles with bounded workspace round-robin admission.

The frozen Run snapshot and execution_sessions are durable intent. Redis only
arbitrates capacity. Reservations last to the Run's native guest expiry; they
are never freed by a short worker or command lease.
"""

import json
import time

from redis.exceptions import RedisError

from app.ports.execution import ExecutionBusy, ExecutionNotStarted

# Keys: host, consumer, workspace, reservation, waiters, workspace grants, costs.
# Args: now, expiry, ttl, id, member, owner, profiles, host/consumer/workspace limits,
#       track consumer/workspace, workspace identity.
_RESERVE = """
local now, expiry, ttl = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local id, member, owner = ARGV[4], ARGV[5], ARGV[6]
local profiles = cjson.decode(ARGV[7])
local count = #profiles
for i=1,3 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now) end
local exists = true
for i=1,count do
  if not redis.call('ZSCORE', KEYS[1], id .. ':' .. i) then exists = false end
end
if exists then
  local held = redis.call('HGET', KEYS[4], member)
  if held and held ~= owner then return -4 end
  if member ~= '' then redis.call('HSET', KEYS[4], member, owner) end
  return member == 'run' and 1 or count
end
local workspace = ARGV[13]
local queue = redis.call('HGETALL', KEYS[5])
local queued, workspace_count = false, 0
local entries = {}
for i=1,#queue,2 do
  local item = cjson.decode(queue[i+1])
  if item.expires <= now then
    redis.call('HDEL', KEYS[5], queue[i])
  else
    entries[#entries+1] = {id=queue[i], data=item}
    if queue[i] == id then queued = true end
    if item.workspace == workspace then workspace_count = workspace_count + 1 end
  end
end
if not queued then
  if #entries >= 1000 or workspace_count >= 100 then return -6 end
  local item = {workspace=workspace, consumer=ARGV[14], count=count, arrived=now, expires=math.min(expiry,now+300000)}
  redis.call('HSET', KEYS[5], id, cjson.encode(item))
  entries[#entries+1] = {id=id, data=item}
end
redis.call('PEXPIRE', KEYS[5], 360000)
local selected, selected_grant = nil, nil
for _, item in ipairs(entries) do
  local wkey = ARGV[18] .. ':workspace:' .. item.data.workspace
  redis.call('ZREMRANGEBYSCORE', wkey, '-inf', now)
  local fits = redis.call('ZCARD', wkey) + item.data.count <= tonumber(ARGV[10])
  if item.data.consumer ~= '' then
    local ckey = ARGV[18] .. ':consumer:' .. item.data.consumer
    redis.call('ZREMRANGEBYSCORE', ckey, '-inf', now)
    fits = fits and redis.call('ZCARD', ckey) + item.data.count <= tonumber(ARGV[9])
  end
  if fits then
  local grant = tonumber(redis.call('HGET', KEYS[6], item.data.workspace) or '0')
  if not selected or grant < selected_grant or
     (grant == selected_grant and (item.data.arrived < selected.data.arrived or
      (item.data.arrived == selected.data.arrived and item.id < selected.id))) then
    selected, selected_grant = item, grant
  end
  end
end
if tonumber(ARGV[8]) > 0 and redis.call('ZCARD', KEYS[1]) + count > tonumber(ARGV[8]) then return -1 end
if ARGV[11] == '1' and redis.call('ZCARD', KEYS[2]) + count > tonumber(ARGV[9]) then return -2 end
if ARGV[12] == '1' and redis.call('ZCARD', KEYS[3]) + count > tonumber(ARGV[10]) then return -3 end
if not selected or selected.id ~= id then return -5 end
local costs = cjson.decode(ARGV[17])
local cpu, memory = 0, 0
for _, token in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
  local saved = redis.call('HGET', KEYS[7], token)
  local cost = saved and cjson.decode(saved) or {2,2048}
  cpu, memory = cpu + cost[1], memory + cost[2]
end
for _, cost in ipairs(costs) do cpu, memory = cpu + cost[1], memory + cost[2] end
if tonumber(ARGV[15]) > 0 and memory > tonumber(ARGV[15]) then return -7 end
if tonumber(ARGV[16]) > 0 and cpu > tonumber(ARGV[16]) then return -8 end
for i=1,count do
  local token = id .. ':' .. i
  redis.call('ZADD', KEYS[1], expiry, token)
  redis.call('HSET', KEYS[7], token, cjson.encode(costs[i]))
  if ARGV[11] == '1' then redis.call('ZADD', KEYS[2], expiry, token) end
  if ARGV[12] == '1' then redis.call('ZADD', KEYS[3], expiry, token) end
end
if redis.call('PTTL', KEYS[7]) < ttl then redis.call('PEXPIRE', KEYS[7], ttl) end
for i=1,3 do
  if redis.call('PTTL', KEYS[i]) < ttl then redis.call('PEXPIRE', KEYS[i], ttl) end
end
if member ~= '' then redis.call('HSET', KEYS[4], member, owner) end
redis.call('PEXPIRE', KEYS[4], ttl)
redis.call('HDEL', KEYS[5], id)
redis.call('HSET', KEYS[6], workspace, now)
redis.call('PEXPIRE', KEYS[6], 360000)
return member == 'run' and 1 or count
"""

_RELEASE_MEMBER = """
if redis.call('HGET', KEYS[1], ARGV[1]) == ARGV[2] then
  redis.call('HDEL', KEYS[1], ARGV[1])
end
return 1
"""

_RELEASE = """
redis.call('HDEL', KEYS[5], ARGV[1])
if redis.call('HLEN', KEYS[4]) > 0 then return 0 end
for i=1,2 do
  local token = ARGV[1] .. ':' .. i
  for j=1,3 do redis.call('ZREM', KEYS[j], token) end
  redis.call('HDEL', KEYS[6], token)
end
redis.call('DEL', KEYS[4])
return 1
"""

REASONS = {
    -1: "host_capacity",
    -2: "consumer_quota",
    -3: "workspace_quota",
    -4: "environment_owned",
    -5: "fair_queue",
    -6: "queue_full",
    -7: "memory_budget",
    -8: "cpu_budget",
}

RESOURCE_COSTS = {"small": (1, 512), "standard": (1, 1024), "heavy": (2, 2048)}

_RESTORE = """
local now = tonumber(ARGV[1])
for _, item in ipairs(cjson.decode(ARGV[2])) do
  local ttl = item.expiry - now
  if ttl > 0 then
    for _, key in ipairs({item.host and KEYS[1] or '', item.consumer, item.workspace}) do
      if key ~= '' then
        redis.call('ZADD', key, 'GT', item.expiry, item.token)
        if redis.call('PTTL', key) < ttl then redis.call('PEXPIRE', key, ttl) end
      end
    end
    if item.host then
      redis.call('HSET', KEYS[2], item.token, cjson.encode(item.cost))
      if redis.call('PTTL', KEYS[2]) < ttl then redis.call('PEXPIRE', KEYS[2], ttl) end
    end
    if item.group ~= '' and item.member ~= '' then
      redis.call('HSETNX', item.group, item.member, item.owner)
      if redis.call('PTTL', item.group) < ttl then redis.call('PEXPIRE', item.group, ttl) end
    end
  end
end
return 1
"""


async def restore_capacity(capacity, records):
    """Rebuild missing slots from committed guest/create intents, conservatively."""
    from datetime import UTC

    items = []
    for record in records:
        expires = record.expires_at
        expiry = round(
            (expires if expires.tzinfo else expires.replace(tzinfo=UTC)).timestamp()
            * 1000
        )
        group = record.capacity_reservation
        profiles = group.get("profiles", [])
        tokens = (
            [
                (f"{group['id']}:{i + 1}", RESOURCE_COSTS[profile])
                for i, profile in enumerate(profiles)
            ]
            if group
            else [
                (
                    record.capacity_token or f"recovered:{record.id}",
                    RESOURCE_COSTS["heavy"],
                )
            ]
        )
        for token, cost in tokens:
            items.append(
                {
                    "host": getattr(record, "host_id", capacity.host_id)
                    == capacity.host_id,
                    "token": token,
                    "cost": cost,
                    "expiry": expiry,
                    "workspace": capacity._scope_key("workspace", record.workspace_id)
                    if record.workspace_id
                    else "",
                    "consumer": capacity._scope_key("consumer", record.consumer_key)
                    if record.consumer_key
                    else "",
                    "group": f"{capacity.key}:reservation:{group['id']}"
                    if group
                    and getattr(record, "host_id", capacity.host_id) == capacity.host_id
                    else "",
                    "member": group.get("member", ""),
                    "owner": group.get("owner", ""),
                }
            )
    try:
        async with capacity._redis() as redis:
            await redis.eval(
                _RESTORE,
                2,
                capacity.key,
                f"{capacity.key}:costs",
                round(time.time() * 1000),
                json.dumps(items),
            )
    except (RedisError, OSError) as exc:
        raise ExecutionNotStarted(
            "OpenSandbox capacity reconciliation is unavailable."
        ) from exc


async def acquire_reservation(capacity, lifetime, scope):
    reservation = scope.reservation
    profiles = reservation["profiles"]
    member = reservation["member"]
    if (
        not 1 <= len(profiles) <= 2
        or member not in {"", "run", "mcp"}
        or (member == "mcp" and len(profiles) != 2)
    ):
        raise ExecutionNotStarted("Frozen sandbox resource requirements are invalid.")
    now = round(time.time() * 1000)
    ttl = max(1, round(lifetime * 1000))
    try:
        async with capacity._redis() as redis:
            admitted = await redis.eval(
                _RESERVE,
                7,
                capacity.key,
                capacity._scope_key("consumer", scope.consumer_key),
                capacity._scope_key("workspace", scope.workspace_key),
                f"{capacity.key}:reservation:{reservation['id']}",
                f"{capacity.key}:waiting",
                f"{capacity.key}:grants",
                f"{capacity.key}:costs",
                now,
                now + ttl,
                ttl,
                reservation["id"],
                member,
                reservation["owner"],
                json.dumps(profiles),
                capacity.limit,
                capacity.consumer_limit,
                capacity.workspace_limit,
                "1" if scope.consumer_key else "0",
                "1" if scope.workspace_key else "0",
                scope.workspace_key or "ephemeral",
                scope.consumer_key or "",
                capacity.memory_limit,
                capacity.cpu_limit,
                json.dumps([RESOURCE_COSTS[profile] for profile in profiles]),
                capacity.scope_prefix,
            )
    except (RedisError, OSError) as exc:
        raise ExecutionNotStarted(
            "OpenSandbox capacity tracking is unavailable."
        ) from exc
    if admitted < 0:
        raise ExecutionBusy(
            "Waiting for execution resources.",
            reason=REASONS[admitted],
            resources={"profiles": profiles, "guests": len(profiles)},
        )
    return f"{reservation['id']}:{admitted}"


async def release_member(capacity, scope):
    reservation = scope.reservation
    try:
        async with capacity._redis() as redis:
            await redis.eval(
                _RELEASE_MEMBER,
                1,
                f"{capacity.key}:reservation:{reservation['id']}",
                reservation["member"],
                reservation["owner"],
            )
    except (RedisError, OSError):
        # Retaining capacity is safe; the native expiry remains the upper bound.
        return
    if reservation.get("ephemeral"):
        await release_reservation(capacity, reservation["id"], scope)


async def release_reservation(capacity, reservation_id, scope):
    try:
        async with capacity._redis() as redis:
            released = await redis.eval(
                _RELEASE,
                6,
                capacity.key,
                capacity._scope_key("consumer", scope.consumer_key),
                capacity._scope_key("workspace", scope.workspace_key),
                f"{capacity.key}:reservation:{reservation_id}",
                f"{capacity.key}:waiting",
                f"{capacity.key}:costs",
                reservation_id,
            )
        if released:
            from app.infra.execution.wakeup import notify_capacity_released

            await notify_capacity_released(capacity)
    except (RedisError, OSError):
        return
