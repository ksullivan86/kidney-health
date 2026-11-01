/* Kidney Diet Log — settings registry and precedence: the browser twin of app/settings_registry.py
   and the read side of app/settings_store.py (note 07 §4.11).

   The Settings view uses DEFS for labels, help texts and the choices of each key (the server's
   GET /api/admin/settings sends only values, sources and locks); the demo API (js/mock/settings.js)
   uses the same table and the precedence functions below to answer like the server.

   Precedence: env lock (read-only, source "env") > the person's own value (scopes user and
   user_default) > the instance value > the registry default. A variable named in
   SETTINGS_INITIAL_ONLY is a first value the server writes once (note 20), never a lock.

   Parity: tests/data/settings_vectors.json is generated from the Python registry and store
   (tests/data/gen_settings_vectors.py); pytest checks it is current and node
   tests/js/run_vectors.mjs replays it against this file. Plain script, no DOM: it also runs in
   a bare V8 context. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  // type: 'bool' | 'int' (min/max) | 'num' (a float in lax mode: min/max, never inf or nan) | 'str' (minLength/maxLength/pattern, stripped
  //       unless strip: false) | 'choice' (options) | 'object' (a pydantic model with extra="forbid": `fields`, each a scalar type above
  //       or 'list' of one). A key with `nullable: true` also takes null (pydantic `X | None`).
  const DEFS = [
    // Optional AI (note 04 R4, §9 A5–A7; app/settings_registry.py "Note 04"). Providers and keys are rows of
    // ai_providers, never settings: the person's `ai` object has no key field (§9 A6).
    { key: 'ai', type: 'object', model: 'AiPreferences', scope: 'user', env: null,
      default: { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '', trust: 'ask' },
      fields: [
        { name: 'opt_in', type: 'bool', default: false },
        { name: 'provider', type: 'str', pattern: '^(auto|own|shared:[1-9][0-9]{0,17})$', strip: false, default: 'auto' },
        { name: 'share_age_sex', type: 'bool', default: false },
        { name: 'preferences', type: 'str', maxLength: 200, default: '' },
        { name: 'trust', type: 'str', pattern: '^(ask|conversation|always)$', strip: false, default: 'ask' },
      ],
      label: 'AI features', help: 'opt_in, provider (auto, own or shared:<id>), share_age_sex, preferences (at most 200 characters) and trust (ask, conversation or always).' },
    { key: 'ai.allow_trusted_saves', type: 'bool', default: false, scope: 'instance', env: 'AI_ALLOW_TRUSTED_SAVES',
      label: 'Let people trust Ask to save without asking',
      help: 'Off by default. Needs the AI assistant (Ask AI) on. When on, a person can choose in Settings → AI features to let the AI assistant save food and recipes at once (for one conversation, or always), after a warning. '
        + 'Off: Ask always shows a card and saves only when the person presses Save. Either way the app\'s numbers, the low and emergency rules and the dose checks stay on, and every save can be undone.' },
    { key: 'ai.allow_user_base_url', type: 'bool', default: false, scope: 'instance', env: 'AI_ALLOW_USER_BASE_URL',
      label: 'People may enter their own AI server address', help: 'Only https on port 443 to public addresses. Off by default; always off when AI_HTTP_PROXY is set.' },
    { key: 'ai.audit_retention_days', type: 'int', min: 0, max: 365, default: 30, scope: 'instance', env: 'AI_AUDIT_RETENTION_DAYS',
      label: 'Keep what was sent to and received from AI for (days)', help: 'Each person sees their own AI activity in Settings. 0 keeps only the time, provider and outcome. Backups keep it until they expire.' },
    { key: 'ai.chat_enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_CHAT_ENABLED',
      label: 'Ask (a chat with the AI inside the app)',
      help: 'Off by default. Needs AI on. When on, people who opted in get an Ask screen: they type a question, the AI looks up the app\'s own numbers, and the app checks the answer before it is shown. '
        + 'Lows and emergencies are answered by the app\'s rules without asking the AI. Each question can use several AI calls.' },
    { key: 'ai.enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_ENABLED',
      label: 'Optional AI features', help: 'Off by default. When on, people who opt in can ask an AI provider you set up for meal ideas and photo help. The rules always run first and check every AI idea; nothing is sent anywhere while this is off.' },
    { key: 'ai.max_concurrency', type: 'int', min: 1, max: 32, default: 2, scope: 'instance', env: 'AI_MAX_CONCURRENCY',
      label: 'AI calls at the same time (whole server)', help: 'Each person has at most one call running. Extra calls are told to try again in a few seconds.' },
    // Design note 32: the server switch for a person's own choice of the server's local or cloud AI (users.can_choose_ai is the per-person tick).
    { key: 'ai.person_route_choice', type: 'bool', default: false, scope: 'instance', env: 'AI_PERSON_ROUTE_CHOICE_ENABLED',
      label: 'Let chosen people pick the server\'s local or cloud AI',
      help: 'Off by default. When on, a person you tick in Server administration → Users (May choose the server\'s local or cloud AI) can choose, for each AI feature, the server\'s local AI or its cloud AI in Settings → AI features. '
        + 'A feature you switched off stays off, and lab report photos always stay on the local AI. Off: everyone uses your routing.' },
    { key: 'ai.recipe_steps', type: 'bool', default: false, scope: 'instance', env: 'AI_RECIPE_STEPS',
      label: 'Cooking steps written by AI in AI recipes',
      help: 'Off by default. When on, an AI recipe may come with up to 8 cooking steps. The app removes any step that talks about medicines, a low, nutrients or amounts, and labels the rest as not checked for cooking times or food safety. '
        + 'Turn it on only after a live run with your model (docs/ai.md).' },
    // Which shared AI each feature uses (privacy tiers, tier 1; app/ai/routing.py). Set in Server administration → AI providers, through PUT /api/admin/ai-routing.
    { key: 'ai.route.chat', type: 'choice', options: ['local', 'cloud', 'off', 'any'], default: 'local', scope: 'instance', env: 'AI_ROUTE_CHAT',
      label: 'Which AI answers in Ask', help: 'local, cloud, off or any. Default local. Needs Ask (ai.chat_enabled) on as well.' },
    { key: 'ai.route.cloud_provider', type: 'int', min: 0, max: 1000000000, default: 0, scope: 'instance', env: null,
      label: 'The cloud AI (shared provider id)', help: 'The shared provider that runs outside your network (0: none). Set it in Server administration → AI providers, not here.' },
    { key: 'ai.route.describe', type: 'choice', options: ['local', 'cloud', 'off', 'any', 'local_then_cloud'], default: 'local', scope: 'instance', env: 'AI_ROUTE_DESCRIBE',
      label: 'Which AI turns a described meal into search words', help: 'local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app\'s checks). Default local.' },
    { key: 'ai.route.labs', type: 'choice', options: ['local', 'off'], default: 'local', scope: 'instance', env: 'AI_ROUTE_LABS',
      label: 'Which AI reads a photo of a lab report', help: 'local or off, never cloud: a lab report can show a name, a date of birth and record numbers that cannot be removed from a photo, so it is read only by the local AI. Default local: with no local AI the feature is off.' },
    { key: 'ai.route.local_provider', type: 'int', min: 0, max: 1000000000, default: 0, scope: 'instance', env: null,
      label: 'The local AI (shared provider id)', help: 'The shared provider that runs on your own network (0: none). Only a provider whose host is in AI_PRIVATE_HOSTS can be local. Set it in Server administration → AI providers, not here.' },
    { key: 'ai.route.meal_ideas', type: 'choice', options: ['local', 'cloud', 'off', 'any', 'local_then_cloud'], default: 'local', scope: 'instance', env: 'AI_ROUTE_MEAL_IDEAS',
      label: 'Which AI suggests meals (ideas, order, swaps, day plan)', help: 'local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app\'s checks). Default local.' },
    { key: 'ai.route.photos', type: 'choice', options: ['local', 'cloud', 'off', 'any', 'local_then_cloud'], default: 'local', scope: 'instance', env: 'AI_ROUTE_PHOTOS',
      label: 'Which AI reads photos (labels and plates)', help: 'local, cloud, off, any (any shared provider a person chose, as before routing) or local_then_cloud (the local AI first; the cloud AI only when the local answer fails the app\'s checks). A kitchen photo can show more than a label, so the default is local: with no local AI the feature is off.' },
    { key: 'ai.route.recipes', type: 'choice', options: ['local', 'cloud', 'off', 'any', 'local_then_cloud'], default: 'local', scope: 'instance', env: 'AI_ROUTE_RECIPES',
      label: 'Which AI suggests and reworks recipes', help: 'local, cloud, off, any or local_then_cloud (the cloud AI only when the local answer fails the app\'s checks). Default local. It sends the foods and amounts of a recipe, never its name, note, steps or link.' },
    // The person's choice per feature (no lab report photos: they stay local or off); written only through PUT /api/me/ai/route-choice.
    { key: 'ai.route_choice', type: 'object', model: 'AiRouteChoice', scope: 'user', env: null,
      default: { photos: 'default', meal_ideas: 'default', describe: 'default', chat: 'default', recipes: 'default' },
      fields: [
        { name: 'photos', type: 'choice', options: ['default', 'local', 'cloud'], default: 'default' },
        { name: 'meal_ideas', type: 'choice', options: ['default', 'local', 'cloud'], default: 'default' },
        { name: 'describe', type: 'choice', options: ['default', 'local', 'cloud'], default: 'default' },
        { name: 'chat', type: 'choice', options: ['default', 'local', 'cloud'], default: 'default' },
        { name: 'recipes', type: 'choice', options: ['default', 'local', 'cloud'], default: 'default' },
      ],
      label: 'Which of the server\'s AIs each feature uses for me',
      help: 'photos, meal_ideas, describe, chat and recipes: default (your admin\'s choice), local or cloud. Counts only when your admin lets you choose.' },
    { key: 'ai.shared_daily_limit', type: 'int', min: 0, max: 100000, default: 30, scope: 'instance', env: 'AI_SHARED_DAILY_LIMIT',
      label: 'Shared AI calls per person per day', help: 'Counts meal ideas, described meals, photos and connection tests on shared providers. 0 means unlimited.' },
    { key: 'ai.user_keys_allowed', type: 'bool', default: true, scope: 'instance', env: 'AI_ALLOW_USER_KEYS',
      label: 'People may use their own AI key', help: 'For OpenAI, OpenRouter or Nous Portal. Their key is encrypted and never shown again.' },
    { key: 'ai.vision_allow_agent', type: 'bool', default: false, scope: 'instance', env: 'AI_VISION_ALLOW_AGENT',
      label: 'Allow photos to go to a Hermes agent', help: 'Off by default. Text printed on a package could try to instruct an agent; even when on, the app only uses a Hermes profile whose tool check passes.' },
    { key: 'ai.vision_plate_enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_VISION_PLATE_ENABLED',
      label: 'Plate photos (AI estimate of what is on a plate)', help: 'Off by default. Needs a provider with a vision model. Portion estimates from photos are rough: the app says so on every result and never logs them without a tap.' },
    { key: 'ai.voice_enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_VOICE_ENABLED',
      label: 'Voice input for Ask (a microphone button)',
      help: 'Off by default. Needs the AI assistant (Ask AI) on and a transcription server set with STT_BASE_URL. When on, people can record a question; the recording goes to that server to become text, '
        + 'is deleted at once, and the text appears in the box for them to read and edit before anything is sent to the AI.' },
    // Assistant access (docs/dev/plans/assistant-step1.md part A; app/auth/api_tokens.py). The tokens are rows of
    // api_tokens, never settings.
    { key: 'assistant.enabled', type: 'bool', default: false, scope: 'instance', env: 'ASSISTANT_ENABLED',
      label: 'Outside AI apps (personal tokens for an AI chat app)',
      help: 'Off by default. When on, each person can make tokens in Settings → Outside AI apps that let a chat assistant they connect read their own food log and targets and, if the person allows it for that token, also save food and recipes. '
        + 'While off, no token can be made or used; turned on again, tokens that have not expired or been revoked work again.' },
    { key: 'audit.retention_days', type: 'int', min: 1, max: 3650, default: 365, scope: 'instance', env: 'AUDIT_RETENTION_DAYS',
      label: 'Keep the activity log for (days)', help: '' },
    // Sign-in with an OpenID Connect provider (design note 24 §4; app/auth/oidc_api.py). The connection is env only.
    { key: 'auth.oidc.admin_groups', type: 'str', maxLength: 500, pattern: '^[^\\x00-\\x1f\\x7f]*$', default: '', scope: 'instance', env: 'OIDC_ADMIN_GROUPS',
      label: 'Provider groups that make someone an admin',
      help: 'A comma list of group names, for example authentik Admins. Empty: roles are set here only. When set, and the provider sends a groups claim, the role follows it at each sign-in: in a listed group means admin, otherwise user. The last admin is never demoted.' },
    { key: 'auth.oidc.allow_signup', type: 'bool', default: false, scope: 'instance', env: 'OIDC_ALLOW_SIGNUP',
      label: 'Make an account for someone new who signs in with the provider',
      help: 'Off by default: only people who already have an account (and linked it), or who have an invite link, get in. Turn it on only for a provider where you choose who has an account, such as your own Authentik. With Google, anyone in the world has an account: then also set the allowed email domains.' },
    { key: 'auth.oidc.allowed_domains', type: 'str', maxLength: 500, pattern: '^[A-Za-z0-9., -]*$', default: '', scope: 'instance', env: 'OIDC_ALLOWED_DOMAINS',
      label: 'Only let in email addresses from these domains',
      help: 'A comma list, for example example.org, family.net. Empty: any address. When set, the provider must say the email is verified. With Google, only Workspace accounts of a listed domain get in: a personal Google account with a work address does not.' },
    { key: 'auth.oidc.button_label', type: 'str', minLength: 1, maxLength: 60, pattern: '^[^\\x00-\\x1f\\x7f]+$', default: 'Sign in with single sign-on', scope: 'instance', env: 'OIDC_BUTTON_LABEL',
      label: 'Words on the single sign-on button',
      help: 'Shown on the sign-in page when sign-in with a provider is on (OIDC_ENABLED). For example: Sign in with Authentik, or Sign in with Google.' },
    { key: 'auth.oidc.link_by_email', type: 'bool', default: false, scope: 'instance', env: 'OIDC_LINK_BY_EMAIL',
      label: 'Give someone the account you made for their email address',
      help: 'Off by default. When on, someone the provider says has a verified email gets the account you made for them in People with that email as its username, if nobody has used it yet (no password, passkey or link). The address must match exactly, in plain letters. Never an admin account, an account someone registered themselves, or an unverified email.' },
    // Two-step sign-in for admins (design note 17 §10; app/auth/deps.py require_admin).
    { key: 'auth.require_two_step_admins', type: 'bool', default: false, scope: 'instance', env: 'AUTH_REQUIRE_TWO_STEP_ADMINS',
      label: 'Admins must use two-step sign-in',
      help: 'Off by default. When on, an admin must use two-step sign-in (a code from an authenticator app) to open Server administration. An admin without it can still use the app and turns it on in Settings → Account → Two-step sign-in. Has no effect when a sign-in proxy or no sign-in is used. You can turn it on only after turning on your own two-step sign-in.' },
    // Weight and blood pressure (note 10 §4.3; app/settings_registry.py "Note 10"). The alarm and the goal are the numbers the person's care
    // team gave them: no default, and the app never suggests either.
    { key: 'body.bp_goal', type: 'object', model: 'BpGoal', scope: 'user', env: null,
      default: { systolic: null, diastolic: null },
      fields: [
        { name: 'systolic', type: 'int', min: 80, max: 200, nullable: true, default: null },
        { name: 'diastolic', type: 'int', min: 40, max: 130, nullable: true, default: null },
      ],
      // The model validator: a goal "under 130/80" has a top number above the bottom one (runs when every field is valid).
      check(out) { return out.systolic != null && out.diastolic != null && out.systolic <= out.diastolic ? 'systolic must be greater than diastolic' : null; },
      label: 'My blood pressure goal (from my care team)',
      help: 'systolic (80–200) and diastolic (40–130), or null for none. The app never suggests a goal: enter the numbers your team gave you.' },
    { key: 'body.weight_alarm', type: 'object', model: 'WeightAlarm', scope: 'user', env: null,
      default: { amount_kg: null, over: 'days', days: 1 },
      fields: [
        { name: 'amount_kg', type: 'num', min: 0.2, max: 10, nullable: true, default: null },
        { name: 'over', type: 'choice', options: ['between_sessions', 'days'], default: 'days' },
        { name: 'days', type: 'int', min: 1, max: 7, default: 1 },
      ],
      label: 'My weight-gain alarm (from my care team)',
      help: 'amount_kg (0.2–10, or null for none), over (between_sessions, on hemodialysis, or days) and days (1–7). The app never suggests a number: enter the one your team gave you.' },
    // Connected devices (design notes 27 and 28; app/devices/). The provider apps (WITHINGS_*, WHOOP_*) are env only, never settings.
    { key: 'devices.enabled', type: 'bool', default: false, scope: 'instance', env: 'DEVICES_ENABLED',
      label: 'Let people connect a Withings scale, a blood pressure monitor or a Whoop strap',
      help: 'Off by default. When on, each person can connect their own Withings or Whoop account in Settings → Connected devices. The server then fetches that person\'s weight, blood pressure and pulse from Withings, and their calories burned, strain, recovery, heart rate variability, sleep and workouts from Whoop, every few hours. Nothing about the person is sent to either company. The server owner sets up a developer app with each company first (WITHINGS_ENABLED, WHOOP_ENABLED; see docs/devices.md). While off, nothing is fetched and the section is hidden; turned on again, connections that were not removed work again.' },
    { key: 'devices.sync_hours', type: 'int', min: 1, max: 24, default: 4, scope: 'instance', env: 'DEVICES_SYNC_HOURS',
      label: 'Fetch from connected devices every (hours)', help: 'How often the server asks Withings and Whoop for new data. People can also press Sync now.' },
    { key: 'food.barcode_negative_ttl_hours', type: 'int', min: 1, max: 720, default: 24, scope: 'instance', env: 'BARCODE_NEGATIVE_TTL_HOURS',
      label: 'Remember barcodes that were not found for (hours)',
      help: 'A barcode that Open Food Facts or USDA did not know is not asked again for this long.' },
    { key: 'food.off_consent', type: 'bool', default: false, scope: 'user', env: null,
      label: 'Send barcodes I scan to Open Food Facts',
      help: 'Your own choice, used only when the admin has turned Open Food Facts lookups on.' },
    { key: 'food.off_contact', type: 'str', minLength: 3, maxLength: 200, pattern: '^[\\x20-\\x27\\x2a-\\x5b\\x5d-\\x7e]+$',
      default: 'https://github.com/ksullivan86/kidney-health', scope: 'instance', env: 'OFF_CONTACT',
      label: 'Contact sent to Open Food Facts',
      help: 'Goes into the User-Agent of every lookup, as Open Food Facts asks of API users. An admin email address is better than '
        + 'the default project address. Letters, digits and punctuation only (no round brackets or backslash).' },
    { key: 'food.off_enabled', type: 'bool', default: false, scope: 'instance', env: 'OFF_ENABLED',
      label: 'Look up barcodes with Open Food Facts',
      help: "Off by default. When on, a barcode that is not in this server's food list is looked up at world.openfoodfacts.org "
        + '(only the barcode number is sent). Product data is under the Open Database License.' },
    { key: 'food.off_rate_per_minute', type: 'int', min: 1, max: 15, default: 10, scope: 'instance', env: 'OFF_RATE_PER_MINUTE',
      label: 'Open Food Facts lookups per minute (whole server)',
      help: 'Open Food Facts allows 15 product lookups a minute from one address and may block an address that sends more. '
        + 'Everyone on this server shares this budget; products already looked up do not count.' },
    { key: 'food.scan_prefer_camera', type: 'bool', default: true, scope: 'user', env: null,
      label: 'Start the camera when I open Scan',
      help: 'On a secure (HTTPS) address the Scan sheet starts the live camera at once. Off: it waits for you to choose the camera, a photo or typing the digits.' },
    { key: 'food.usda_branded_barcode', type: 'bool', default: true, scope: 'instance', env: 'USDA_BRANDED_BARCODE',
      label: 'Also look barcodes up in USDA FoodData Central',
      help: "Uses the person's USDA key or the shared one, when Open Food Facts does not know a product, has no nutrition facts "
        + 'for it, or lacks potassium or sodium for a US product.' },
    // Meal guidance (note 06 §4.14; note 09 §4.2; app/settings_registry.py GuidancePreferences). Food preferences are not here:
    // they are rows of food_preferences (PUT/DELETE /api/guidance/preferences/{food_id}, aliases /not-for-me/{food_id}).
    { key: 'guidance', type: 'object', model: 'GuidancePreferences', scope: 'user', env: null,
      default: { enabled: true, carb_tolerance_g: 10, hypo_dose_g: 15, exclude_categories: [], show_plan_builder: true, show_insights: true, ai_enrich: false,
        learn_from_log: true, like_categories: [], less_categories: [], hidden_usual_meals: [], plan_repeat_meals: [], plan_snack: false,
        repeat_ok_foods: [], repeat_ok_meals: [] },
      fields: [
        { name: 'enabled', type: 'bool', default: true },
        { name: 'carb_tolerance_g', type: 'int', min: 5, max: 20, default: 10 },
        { name: 'hypo_dose_g', type: 'int', min: 5, max: 30, default: 15 },
        { name: 'exclude_categories', type: 'list', item: { type: 'str', minLength: 1, maxLength: 100 }, maxItems: 50, unique: true, default: [] },
        { name: 'show_plan_builder', type: 'bool', default: true },
        { name: 'show_insights', type: 'bool', default: true },
        { name: 'ai_enrich', type: 'bool', default: false },
        { name: 'learn_from_log', type: 'bool', default: true },
        { name: 'like_categories', type: 'list', item: { type: 'str', minLength: 1, maxLength: 100 }, maxItems: 50, unique: true, default: [] },
        { name: 'less_categories', type: 'list', item: { type: 'str', minLength: 1, maxLength: 100 }, maxItems: 50, unique: true, default: [] },
        // A usual meal's key, "<meal>:<food id>x<quarter servings>,…" (GE.fits.usualMealKey); integers only, so both sides write the same text.
        { name: 'hidden_usual_meals', type: 'list', maxItems: 50, unique: true, default: [],
          item: { type: 'str', minLength: 1, maxLength: 400, pattern: '^(?:breakfast|lunch|dinner|snack):[0-9]+x[0-9]+(?:,[0-9]+x[0-9]+)*$' } },
        // Planning several days (design note 23 §12): the plan sheet's remembered choices and the "OK to repeat" marks.
        { name: 'plan_repeat_meals', type: 'list', maxItems: 4, unique: true, default: [],
          item: { type: 'choice', options: ['breakfast', 'lunch', 'dinner', 'snack'] } },
        { name: 'plan_snack', type: 'bool', default: false },
        { name: 'repeat_ok_foods', type: 'list', maxItems: 200, unique: true, default: [], item: { type: 'int', min: 1, max: 2147483647 } },
        { name: 'repeat_ok_meals', type: 'list', maxItems: 100, unique: true, default: [], item: { type: 'int', min: 1, max: 2147483647 } },
      ],
      // The model validator: a food group is liked, ranked lower or never suggested, not two of them (runs when every field is valid).
      check(out) {
        const seen = new Set();
        const clash = [];
        for (const name of [...out.like_categories, ...out.less_categories, ...out.exclude_categories]) {
          if (seen.has(name) && !clash.includes(name)) clash.push(name);
          seen.add(name);
        }
        return clash.length ? `a food group can be in only one of Like, Less often and Never suggest: ${clash.join(', ')}` : null;
      },
      label: 'Meal guidance preferences', help: 'carb_tolerance_g (5–20) and hypo_dose_g (5–30) come from your diabetes team.' },
    { key: 'guidance.beam_width', type: 'int', min: 1, max: 64, default: 16, scope: 'instance', env: 'GUIDANCE_BEAM_WIDTH',
      label: 'Plan builder: search width', help: 'Partial meals kept at each step. 8 is about 15 % faster and finds slightly worse meals.' },
    { key: 'guidance.enabled', type: 'bool', default: true, scope: 'instance', env: 'GUIDANCE_ENABLED',
      label: 'Meal guidance', help: 'Rule-based suggestions for the next meal, swap ideas, plan-the-day and insights. Works without AI.' },
    { key: 'guidance.plan_days_ai_max', type: 'int', min: 1, max: 90, default: 31, scope: 'instance', env: 'PLAN_DAYS_AI_MAX',
      label: 'Plan several days with AI ideas: most days at once',
      help: 'Each day costs AI calls. Never more than the plain cap. The several-days plan uses no AI yet.' },
    { key: 'guidance.plan_days_max', type: 'int', min: 1, max: 90, default: 60, scope: 'instance', env: 'PLAN_DAYS_MAX',
      label: 'Plan several days: most days at once',
      help: "Plans from the person's own foods, without AI. About 30 ms a day on a laptop; lower it on a small server." },
    { key: 'guidance.pool_per_role', type: 'int', min: 20, max: 2000, default: 200, scope: 'instance', env: 'GUIDANCE_POOL_PER_ROLE',
      label: 'Plan builder: foods considered per role',
      help: 'Lower it (for example to 120) if planning a day is slow on a small server such as a Raspberry Pi 4.' },
    { key: 'instance.name', type: 'str', minLength: 1, maxLength: 80, default: 'Kidney Health', scope: 'instance', env: 'INSTANCE_NAME',
      label: 'Server name', help: 'Shown on the sign-in, invite and password pages, and in Settings under About & privacy.' },
    // Your own list app and recipe import (design note 30; app/list_sync/, app/recipe_import/). LIST_SYNC_ALLOWED_HOSTS is env only.
    { key: 'lists.sync_enabled', type: 'bool', default: false, scope: 'instance', env: 'LIST_SYNC_ENABLED',
      label: 'Let people send the shopping list to their own Grocy, KitchenOwl or Mealie',
      help: 'Off by default. When on, each person can add their own list app\'s address and key in Settings → Shopping list app, then send the Plan\'s shopping list to it. Only the foods\' names and amounts are sent. '
        + 'A list app on a home address works only when the server lists it in LIST_SYNC_ALLOWED_HOSTS (see docs/list-sync.md). While off, nothing is sent and the section is hidden; turned on again, saved addresses work again.' },
    { key: 'providers.usda.daily_limit_per_user', type: 'int', min: 0, max: 100000, default: 200, scope: 'instance', env: 'USDA_SHARED_DAILY_LIMIT',
      label: 'Shared USDA lookups per person per day', help: '0 means unlimited.' },
    { key: 'providers.usda.shared_enabled', type: 'bool', default: true, scope: 'instance', env: 'USDA_SHARED_ENABLED',
      label: "Share the server's USDA key", help: 'Effective only when a shared key is set.' },
    { key: 'providers.usda.user_keys_allowed', type: 'bool', default: true, scope: 'instance', env: 'USDA_ALLOW_USER_KEYS',
      label: 'People may add their own USDA key', help: '' },
    // Phone shortcuts (design note 12; app/auth/api_tokens.py, app/push.py). The device tokens are rows of api_tokens, never settings.
    { key: 'push.enabled', type: 'bool', default: false, scope: 'instance', env: 'PUSH_ENABLED',
      label: 'Let people send weights and blood pressure from a phone shortcut',
      help: 'Off by default. When on, each person can make tokens in Settings → Phone shortcuts; a shortcut on their phone can use one to add weights and blood pressure readings to that person\'s own log. '
        + 'A token can only add: it cannot read or change anything. While off, no token can be made or used; turned on again, tokens that have not expired or been revoked work again.' },
    { key: 'recipes.import_enabled', type: 'bool', default: false, scope: 'instance', env: 'RECIPE_IMPORT_ENABLED',
      label: 'Let people import a recipe from a web page',
      help: 'Off by default. When on, a person can paste a recipe page\'s link in Plan → Import a recipe, and this server reads that page from the internet (never a private address) to find its ingredients and steps. Pasting the ingredients works either way, with no network.' },
    { key: 'registration.invite_ttl_days', type: 'int', min: 1, max: 90, default: 7, scope: 'instance', env: 'INVITE_TTL_DAYS',
      label: 'Invite links expire after (days)', help: '' },
    { key: 'registration.mode', type: 'choice', options: ['invite', 'closed', 'open'], default: 'invite', scope: 'instance', env: 'REGISTRATION_MODE',
      label: 'Registration',
      help: 'invite: admins send single-use links. closed: admins create accounts. open: anyone who reaches the page can register (HTTPS required).' },
    // The Care team (design notes 19 and 25; app/sharing.py). The shares are rows of the shares table, never settings.
    { key: 'sharing.enabled', type: 'bool', default: false, scope: 'instance', env: 'SHARING_ENABLED',
      label: 'Turn on the Care team: people can let family or a dietitian on this server see their log, or help plan meals',
      help: 'Off by default. When on, each person can add someone with an account here to their Care team in Settings → Care team, by user name or with a link. '
        + 'A Viewer can read the parts that were ticked (food log, lab results, weight and blood pressure, symptoms) and never change anything. A Care helper can also plan meals and use the shopping list. '
        + 'Either side can stop it at any time. While off, nobody can see anyone else\'s data; turned on again, Care teams that were not stopped work again.' },
    // Personalised targets and labs (note 05 §4.9; app/settings_registry.py).
    { key: 'targets.default_activity', type: 'choice', options: ['inactive', 'low_active', 'active', 'very_active'], default: 'inactive', scope: 'instance', env: 'DEFAULT_ACTIVITY',
      label: 'Activity level used until a person chooses theirs', help: 'Used for the calorie estimate (2023 Dietary Reference Intakes).' },
    { key: 'targets.lab_fresh_days.albumin', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: 'LAB_FRESH_DAYS_ALBUMIN',
      label: 'An albumin result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.bicarbonate', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: 'LAB_FRESH_DAYS_BICARBONATE',
      label: 'A bicarbonate result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.phosphate', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: 'LAB_FRESH_DAYS_PHOSPHATE',
      label: 'A phosphate result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.potassium', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: 'LAB_FRESH_DAYS_POTASSIUM',
      label: 'A potassium result counts for (days)', help: '' },
    { key: 'targets.lab_rules_enabled', type: 'bool', default: true, scope: 'instance', env: 'LAB_RULES_ENABLED',
      label: 'Let lab results change suggested targets',
      help: 'Off: potassium and phosphorus suggestions use the stage defaults and lab notes are left out. The warning for a very high '
        + 'potassium result is always shown. Keep it off on public demo servers until a clinician has reviewed the lab rules.' },
    // Test accounts (design note 26; app/test_accounts.py). The password is env only (TEST_ACCOUNT_PASSWORD_FILE), never a setting.
    { key: 'test_accounts.ai', type: 'bool', default: false, scope: 'instance', env: 'TEST_ACCOUNT_AI',
      label: 'Let the test accounts use the server\'s AI',
      help: 'Off by default: the AI features are off for test accounts, whatever else is set. When on, they work for test accounts as for everyone else (AI must also be on).' },
    { key: 'test_accounts.enabled', type: 'bool', default: false, scope: 'instance', env: 'TEST_ACCOUNT_ENABLED',
      label: 'Test accounts: let testers sign in as tester and tester-helper',
      help: 'Off by default. When on, the server makes two accounts if they are missing: tester, who starts with the sample person Sam\'s food log, lab results and weights, '
        + 'and tester-helper, a Care helper on tester\'s Care team. Both use the password in the file TEST_ACCOUNT_PASSWORD_FILE. They are never admins, can only be on a Care team '
        + 'with each other, and get a Send feedback button. Turned off, they are disabled and signed out (not deleted); turned on again, they work again. Turn on the Care team too, to test it.' },
    // Tokens that never expire (design note 24 §13; app/auth/api_tokens.py). Both token families.
    { key: 'tokens.allow_never_expiring', type: 'bool', default: true, scope: 'instance', env: 'TOKENS_ALLOW_NEVER_EXPIRING',
      label: 'Let people make tokens that never expire',
      help: 'On by default. When on, a person making a token in Settings → Outside AI apps or Phone shortcuts can choose "Never (until you remove it)" as well as 30 days, 90 days or 1 year. '
        + 'When off, every new token expires. Tokens already made keep working until they are removed; to end them, use Revoke tokens in People.' },
    { key: 'ui.theme', type: 'choice', options: ['system', 'light', 'dark'], default: 'system', scope: 'user_default', env: 'UI_THEME',
      label: 'Theme', help: '' },
    { key: 'user.units.labs', type: 'choice', options: ['us', 'si'], default: 'us', scope: 'user_default', env: 'LAB_UNITS',
      label: 'Units for lab results',
      help: 'us: mg/dL (creatinine, phosphate), g/dL (albumin), mg/g (urine albumin), % (HbA1c). si: µmol/L, mmol/L, g/L, mg/mmol, '
        + 'mmol/mol. Only the unit offered first changes; any unit can still be entered.' },
    { key: 'user.units.weight', type: 'choice', options: ['kg', 'lb'], default: 'lb', scope: 'user_default', env: 'WEIGHT_UNITS',
      label: 'Units for weight',
      help: "lb or kg (the app's US default is lb). Only how a weight is shown and typed changes; weights are stored in kilograms." },
  ];
  const BY_KEY = Object.fromEntries(DEFS.map((d) => [d.key, d]));

  const userEditable = (d) => d.scope === 'user' || d.scope === 'user_default';
  const adminEditable = (d) => d.scope === 'instance' || d.scope === 'user_default';

  // What the UI calls each source (note 07 §4.11; the handbook's "Settings the server locks").
  const SOURCE_LABEL = {
    env: 'Set by the server',
    user: 'Your choice',
    instance: 'Set by your admin',
    default: 'App default',
  };

  function choiceMessage(options) {
    const opts = options.map((o) => `'${o}'`);
    return `Input should be ${opts.length > 1 ? `${opts.slice(0, -1).join(', ')} or ${opts[opts.length - 1]}` : opts[0]}`;
  }
  const BOOL_TRUE = ['1', 'on', 't', 'true', 'y', 'yes'];
  const BOOL_FALSE = ['0', 'off', 'f', 'false', 'n', 'no'];
  // The key's pydantic type in lax mode, as TypeAdapter.validate_python applies it to a JSON value:
  // returns { value } or { error } (the server's InvalidSettingValue text without the "key: " prefix).
  // pydantic-core float from str: Rust's f64 grammar after trimming; on failure it retries with the underscores removed unless one
  // leads, trails or doubles. undefined = unable to parse (js/mock/core.js has the same).
  const PY_SPECIAL_FLOAT = /^[+-]?(?:inf|infinity|nan)$/i;
  const RUST_FLOAT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
  function pydanticFloat(s) {
    const t = s.trim();
    if (PY_SPECIAL_FLOAT.test(t)) return /nan/i.test(t) ? NaN : t[0] === '-' ? -Infinity : Infinity;
    if (RUST_FLOAT.test(t)) return Number(t);
    if (t && !t.startsWith('_') && !t.endsWith('_') && !t.includes('__')) {
      const u = t.replace(/_/g, '');
      if (RUST_FLOAT.test(u)) return Number(u);
    }
    return undefined;
  }
  function validate(def, value) {
    if (def.nullable && value === null) return { value: null };
    switch (def.type) {
      case 'bool': {
        if (typeof value === 'boolean') return { value };
        if (value === 0 || value === 1) return { value: value === 1 };
        if (typeof value === 'number') return { error: Number.isInteger(value) ? 'Input should be a valid boolean, unable to interpret input' : 'Input should be a valid boolean' };
        if (typeof value === 'string') {
          const low = value.trim().toLowerCase();
          if (BOOL_TRUE.includes(low)) return { value: true };
          if (BOOL_FALSE.includes(low)) return { value: false };
          return { error: 'Input should be a valid boolean, unable to interpret input' };
        }
        return { error: 'Input should be a valid boolean' };
      }
      case 'int': {
        let n = value;
        if (typeof value === 'boolean') n = value ? 1 : 0;
        else if (typeof value === 'string') {
          const t = value.trim();
          if (!/^[+-]?\d(?:_?\d)*(?:\.0+)?$/.test(t)) return { error: 'Input should be a valid integer, unable to parse string as an integer' };
          n = Number(t.replace(/_/g, '').replace(/\.0+$/, ''));
        } else if (typeof value !== 'number' || !Number.isFinite(value)) return { error: 'Input should be a valid integer' };
        if (!Number.isInteger(n)) return { error: 'Input should be a valid integer, got a number with a fractional part' };
        if (def.min != null && n < def.min) return { error: `Input should be greater than or equal to ${def.min}` };
        if (def.max != null && n > def.max) return { error: `Input should be less than or equal to ${def.max}` };
        return { value: n };
      }
      case 'num': {
        let n;
        if (typeof value === 'boolean') n = value ? 1 : 0;
        else if (typeof value === 'number') n = value;
        else if (typeof value === 'string') {
          n = pydanticFloat(value);
          if (n === undefined) return { error: 'Input should be a valid number, unable to parse string as a number' };
        } else return { error: 'Input should be a valid number' };
        if (!Number.isFinite(n)) return { error: 'Input should be a finite number' };
        if (def.min != null && n < def.min) return { error: `Input should be greater than or equal to ${def.min}` };
        if (def.max != null && n > def.max) return { error: `Input should be less than or equal to ${def.max}` };
        return { value: n };
      }
      case 'str': {
        if (typeof value !== 'string') return { error: 'Input should be a valid string' };
        const v = def.strip === false ? value : value.trim();
        if (def.minLength != null && v.length < def.minLength) return { error: `String should have at least ${def.minLength} character${def.minLength === 1 ? '' : 's'}` };
        if (def.maxLength != null && v.length > def.maxLength) return { error: `String should have at most ${def.maxLength} characters` };
        if (def.pattern != null && !new RegExp(def.pattern).test(v)) return { error: `String should match pattern '${def.pattern}'` };
        return { value: v };
      }
      case 'choice':
        return def.options.includes(value) ? { value } : { error: choiceMessage(def.options) };
      case 'list': {
        if (!Array.isArray(value)) return { error: 'Input should be a valid list' };
        const errors = [];
        let out = [];
        for (const item of value) {
          const r = validate(def.item, item);
          if (r.error) errors.push(r.error); else out.push(r.value);
        }
        if (errors.length) return { error: errors.join('; ') };
        if (def.maxItems != null && out.length > def.maxItems) {
          return { error: `List should have at most ${def.maxItems} item${def.maxItems === 1 ? '' : 's'} after validation, not ${out.length}` };
        }
        if (def.unique) out = out.filter((x, i) => out.indexOf(x) === i);
        return { value: out };
      }
      case 'object': {
        // pydantic: every field's errors in field order, then one per unknown key in input order, joined by "; ".
        if (value == null || typeof value !== 'object' || Array.isArray(value)) {
          return { error: `Input should be a valid dictionary or instance of ${def.model}` };
        }
        const errors = [];
        const out = {};
        for (const f of def.fields) {
          if (!Object.prototype.hasOwnProperty.call(value, f.name)) { out[f.name] = JSON.parse(JSON.stringify(f.default)); continue; }
          const r = validate(f, value[f.name]);
          if (r.error) errors.push(r.error); else out[f.name] = r.value;
        }
        for (const k of Object.keys(value)) if (!def.fields.some((f) => f.name === k)) errors.push('Extra inputs are not permitted');
        if (!errors.length && def.check) {  // a pydantic model validator (mode "after") runs only when every field is valid
          const msg = def.check(out);
          if (msg) return { error: `Value error, ${msg}` };
        }
        return errors.length ? { error: errors.join('; ') } : { value: out };
      }
      default:
        return { value };
    }
  }

  // An env lock's text as the server parses it (validate_strings): "true"/"false"/"1"/"0"/... for
  // bools, digits for ints, the stripped text otherwise. { value } or { error }.
  function parseEnv(def, raw) {
    const t = String(raw).trim();
    if (def.type === 'bool') {
      const low = t.toLowerCase();
      if (BOOL_TRUE.includes(low)) return { value: true };
      if (BOOL_FALSE.includes(low)) return { value: false };
      return { error: 'Input should be a valid boolean, unable to interpret input' };
    }
    if (def.type === 'int') return /^[+-]?\d+$/.test(t) ? validate(def, Number(t)) : { error: 'Input should be a valid integer' };
    return validate(def, t);
  }

  // ctx = { env: {ENV_NAME: text}, instance: {key: value}, user: {key: value} | null }
  // → { value, source, locked, env }
  function initialOnly(env) {
    const names = String(env.SETTINGS_INITIAL_ONLY || '').split(',').map((n) => n.trim()).filter(Boolean);
    return names.includes('*') ? null : names; // null: every setting's variable
  }
  function effective(def, ctx) {
    const env = (ctx && ctx.env) || {};
    const initial = initialOnly(env);
    const firstValueOnly = def.env && (initial === null || initial.includes(def.env));
    if (def.env && !firstValueOnly && env[def.env] != null && String(env[def.env]).trim() !== '') {
      const parsed = parseEnv(def, env[def.env]);
      if (!parsed.error) return { value: parsed.value, source: 'env', locked: true, env: def.env };
    }
    const user = ctx && ctx.user;
    if (user && userEditable(def) && Object.prototype.hasOwnProperty.call(user, def.key)) {
      const v = validate(def, user[def.key]);
      if (!v.error) return { value: v.value, source: 'user', locked: false, env: def.env || null };
    }
    const inst = (ctx && ctx.instance) || {};
    if (Object.prototype.hasOwnProperty.call(inst, def.key)) {
      const v = validate(def, inst[def.key]);
      if (!v.error) return { value: v.value, source: 'instance', locked: false, env: def.env || null };
    }
    return { value: def.default, source: 'default', locked: false, env: def.env || null };
  }
  // GET /api/me/settings → settings
  function userView(ctx, defs = DEFS) {
    const out = {};
    for (const d of [...defs].sort((a, b) => (a.key < b.key ? -1 : 1))) {
      if (!userEditable(d)) continue;
      const e = effective(d, ctx);
      out[d.key] = { value: e.value, source: e.source, editable: !e.locked };
    }
    return out;
  }
  // GET /api/admin/settings → settings (instance view: no person's own values)
  function adminView(ctx, defs = DEFS) {
    const out = {};
    for (const d of [...defs].sort((a, b) => (a.key < b.key ? -1 : 1))) {
      if (!adminEditable(d)) continue;
      const e = effective(d, { env: ctx && ctx.env, instance: ctx && ctx.instance, user: null });
      out[d.key] = { value: e.value, source: e.source, locked_by_env: e.locked ? d.env : null, scope: d.scope };
    }
    return out;
  }

  KH.settings = { DEFS, BY_KEY, SOURCE_LABEL, userEditable, adminEditable, validate, parseEnv, effective, userView, adminView, choiceMessage };
})();
