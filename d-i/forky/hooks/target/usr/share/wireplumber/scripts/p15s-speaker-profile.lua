-- Prefer an available Speaker profile on the P15s SOF card whenever
-- WirePlumber re-evaluates its UCM profiles. Names come from EnumProfile;
-- microphone/HDMI combinations can change with the packaged UCM definition.
local utils = require ("common-utils")

local function speaker_route_available (device, index)
  local found = false
  for param in device:iterate_params ("EnumRoute") do
    local route = utils.parseParam (param, "EnumRoute")
    if route and route.direction == "Output" and
        (route.name or ""):lower ():find ("speaker", 1, true) then
      local applies = not route.profiles or #route.profiles == 0
      for _, profile in ipairs (route.profiles or {}) do
        applies = applies or profile == index
      end
      if applies then
        found = true
        if route.available ~= "no" then return true end
      end
    end
  end
  -- Older devices may not publish profile/route associations. Preserve the
  -- profile's own availability in that case; never treat an explicit no as yes.
  return not found
end

SimpleEventHook {
  name = "device/prefer-p15s-speaker",
  after = "device/find-stored-profile",
  before = "device/find-preferred-profile",
  interests = {
    EventInterest { Constraint { "event.type", "=", "select-profile" } },
  },
  execute = function (event)
    -- Explicit application/user choices already resolved by earlier hooks
    -- remain usable, including plugged headphones.
    if event:get_data ("selected-profile") then return end
    local device = event:get_subject ()
    if device.properties ["device.name"] ~=
        "alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic" then return end
    local best = nil
    for param in device:iterate_params ("EnumProfile") do
      local profile = utils.parseParam (param, "EnumProfile")
      local name = profile and (profile.name or ""):lower () or ""
      if profile and name:find ("speaker", 1, true) and
          not name:find ("headphone", 1, true) and profile.available ~= "no" and
          speaker_route_available (device, profile.index) and
          (not best or (profile.priority or 0) > (best.priority or 0) or
            ((profile.priority or 0) == (best.priority or 0) and profile.index < best.index)) then
        best = profile
      end
    end
    if best then event:set_data ("selected-profile", best) end
  end,
}:register ()
