# Test the full app: a walk-through with the test accounts

This page is for someone who tests the app on a real server, with two test accounts: **tester** (the patient) and
**tester-helper** (a family member). You don't need to know anything about computers or software. The first part is for the
person who runs the server.

It takes about an hour. You can stop at any point and still send what you have.

## For the person running the server

1. Put a long password in a file and give it to the app as a secret. With Podman:
   `printf '%s' 'a long password of your own' | podman secret create kidney-test-password -`, then uncomment the test account
   lines in `deploy/quadlet/kidney-health.container`. With compose: put it in `deploy/secrets/test_account_password` and
   uncomment `TEST_ACCOUNT_PASSWORD_FILE` and the `test_account_password` secret in `deploy/compose.yaml`.
2. Set `TEST_ACCOUNT_ENABLED=true` and `SHARING_ENABLED=true` (the Care team). If you want testers to try the AI, set
   `TEST_ACCOUNT_AI=true` as well (AI must be on for the server).
3. Restart. **Server administration → Test accounts** shows `tester` and `tester-helper`, both **On**. If it shows a problem
   instead (for example a password that is too short), fix it and restart.
4. Give each tester the server's address, the two user names and the password, and this page.
5. Read what they send in **Server administration → Feedback**. Between testers, press **Reset test accounts**: it puts both
   accounts back to the start and signs them out. The feedback stays.
6. When testing is over, turn the switch off. The accounts are turned off and signed out, not deleted.

To let a tester choose between your local AI and your cloud AI, set `AI_PERSON_ROUTE_CHOICE_ENABLED=true` (with
`TEST_ACCOUNT_AI=true` and both AIs set up) and tick **May choose the server's local or cloud AI** for `tester` in Server
administration → Users. A reset of the test accounts takes the tick away, so tick it again after each reset.

To let testers import recipes from web pages too, set `RECIPE_IMPORT_ENABLED=true` (pasting ingredients works without it). Sending
the list to a list app (`LIST_SYNC_ENABLED`, [list-sync.md](list-sync.md)) is for real accounts only: try it yourself with your
own Grocy, KitchenOwl or Mealie. Testers can try **Open in Instacart** when it is on (`INSTACART_ENABLED` and the server's key,
[instacart.md](instacart.md)): a development key with `INSTACART_BASE_URL=https://connect.dev.instacart.tools` makes test pages.

More detail: [accounts.md](accounts.md#test-accounts).

## For the tester

### Before you start

* You need a phone, and for the last part a second phone or a computer.
* The app comes filled in with a made-up person, **Sam**: CKD stage 4, type 1 diabetes, 70 kg (154 lb), not on dialysis. Use the
  app as if you were Sam, or helping Sam. Other testers use the same accounts, so you may see their changes.
* The app is not medical advice, and nor is this test. Please don't change your own diet based on it.
* **Send feedback** is the speech-bubble button at the top of every screen. Use it as often as you like, even for small things.
  It asks what you were trying to do, what happened, whether the screen was useful, and whether anything looked wrong or unsafe.
  Only what you type is sent, with the name of the screen. Nothing from Sam's log is copied in.

### 1. Sign in and add to the home screen (5 minutes)

* Open the address you were given on your phone and sign in as **tester** with the password.
* Add the app to your home screen: on an iPhone, the Share button, then **Add to Home Screen**; on Android, the menu, then
  **Install app** or **Add to Home screen**. **Settings → This device** shows the steps too.
* Open it from the home screen. Does it feel like an app?

### 2. Today (5 minutes)

Open **Today**.

* What do you think this screen is telling you about Sam's day?
* Can you tell how much potassium, phosphorus, sodium and protein Sam has had, and how much is left?
* Is anything shown as too high? Is it clear why?

### 3. Add a food (10 minutes)

Go to **Add**.

* Search for a food someone with CKD would really eat, for example white bread, an apple, chicken or rice. Choose an amount and
  add it. Did you find it? Was the amount easy to enter?
* Try **Scan a barcode** on something in your kitchen. Did it find the product? If not, what happened?
* Try a food high in potassium, such as a banana or orange juice. Is the warning helpful, too strong, or too weak?

### 4. What fits now (5 minutes)

On **Today**, find **What fits now**.

* Do the suggestions look like foods someone on a kidney diet could really eat? Would a dietitian trust them?

### 5. Treating a low blood sugar (3 minutes)

Sam has type 1 diabetes. Imagine Sam's blood sugar is low and Sam drinks some juice to treat it.

* Log the juice as **Used to treat a low**.
* The app must **never** block a low treatment or warn against it, even when the juice is high in potassium. If it ever does,
  press **Send feedback**, tick **This looked wrong or unsafe**, and say exactly what it said. This matters a lot.

### 6. Plan several days and the shopping list (10 minutes)

Go to **Plan** and find **Plan several days…**. Plan a week.

* Do the planned meals look like real kidney-friendly meals? Is there enough variety?
* Open the **Shopping list**. Could you take it to the store? Try **Copy list** or **Share list**.
* If you plan days by mistake, can you clear them again?

**Import a recipe.** Under **Saved meals**, press **Import a recipe**. Paste a few ingredient lines from a recipe you like, one on
each line (for example `1 lb chicken breast`, `2 cups cooked white rice`, `1 tsp dried thyme`), give it a name and how many
servings it makes, and press **Read ingredients**. If the server can read recipe pages, try a recipe page's link instead.

* Did the app pick the right food for each line? Fix one with **Search for another food…**, and leave one out.
* Is it clear that you must tick **Checked** on every line before you can save, and why?
* Read the sentence about estimates under the numbers. Is it clear?
* Save it. Does it show up under Saved meals, with its link if it came from a page?

**Your own list app.** Test accounts cannot send the list to a list app (a real key must not end up in a shared account), so
**Settings → Shopping list app** says so. If you use Grocy, KitchenOwl or Mealie, try it on the demo page or with your own
account on a server where it is turned on: **Test**, then Plan → Shopping list → **Send**. Is it clear what is sent?

**Open in Instacart.** If Plan → Shopping list has **Open in Instacart**, press it. Read the lines and the sentence about
Instacart's own terms. Untick one food, then press **Send to Instacart**. Does Instacart's page open in a new tab with the foods
you left ticked? If no tab opened, does the button in the sheet open it? You do not need to sign in to Instacart or buy anything.

### 7. Lab results and suggested targets (7 minutes)

Go to **Profile**.

* Do Sam's daily targets look reasonable for stage 4 CKD?
* Press **Suggest targets**. Is the reason for each number clear?
* Open **Lab results** and add a potassium result, for example 5.8. Is what the app says clear and calm, or alarming?

### 8. Trends and Visit prep (5 minutes)

Go to **Trends**.

* Can you see how Sam did over the past week? Which days were over?
* Open **Get ready for a visit** (the **Visit prep** page). Would you bring it to a nephrologist or a dietitian?

### 9. The AI assistant (only if the person running the server turned it on; 5 minutes)

If you see an **Ask AI** tab, try it: ask what Sam could have for dinner.

* It is an AI. It can be wrong, so check what it says.
* It must **never** give an insulin dose or a medicine dose. If it ever does, use **Send feedback**, tick **This looked wrong or
  unsafe**, and copy what it said.

**Choosing the AI** (only if Settings → AI features shows **Choose which AI each feature uses**; 3 minutes).

* Set **Describe a meal** to **The server's cloud AI**, then describe a meal in Add. The first time, a sheet asks before
  anything is sent and names the company. Say yes, and check the answer and Settings → AI features → AI activity name the cloud AI.
* Set it back to **Server default**. The line for it in Settings no longer ends "You chose this."
* **Lab report photos** should not be in the list at all. If they are, use **Send feedback**.

### 10. Plan Sam's meals as a family member (10 minutes)

On a second phone or a computer, open the same address and sign in as **tester-helper**. This is Jo, who helps Sam with meals.

* Go to **Settings → Care team**. Under **Care teams you are on**, you should see Sam, as a **Care helper**.
* Press **Plan meals** (or **Planning for** at the top of the **Plan** tab). Is it clear that you are changing Sam's plan, not
  your own? Add a food to tomorrow, then press **Back to my own plan**.
* Back on the first phone, as **tester**: open tomorrow on **Today**. Does the food say **Added by Jo**?
* As **tester**, open **Settings → Care team** and change Jo's **Role** to **Viewer**. On the second phone, can Jo still plan
  Sam's meals? (Jo should only be able to look.) Then change it back to **Care helper**.

### 11. Jo logs food, uses a saved meal and suggests one (10 minutes)

Sam and Jo stay on the same two phones. Sam chooses what Jo may do; Jo tries it.

* As **tester**, open **Settings → Care team → What Jo may see and do**. Tick **Log food I ate**. Does the role now say
  **Caregiver**? Then tick **Use my saved meals** and **Suggest meals for me to add**. The role should now say **Custom**.
  Is it clear what each switch does?
* As **tester-helper**, open the **Plan** tab and choose Sam under **Planning for**. Does the banner say that what Jo adds
  goes into Sam's food log?
* Pick today. Add a food and choose **Eaten**. On a planned food, press **Mark eaten**.
* Under **Sam's saved meals**, press **Add to plan** on one meal.
* If Sam has a low treatment on that day (glucose tablets or juice), does it say only Sam can change it, with no buttons?
* Under **Suggest a meal**, add one or two foods for dinner tomorrow and a short note, then press **Send to Sam**. Does the app
  show how it fits Sam's day? Try a note that mentions insulin. It should be refused with a plain reason.
* As **tester**, open the **Plan** tab. Is Jo's suggestion at the top? Press **Add to my plan**. Is it now on tomorrow's plan?
* As **tester**, open **Today**. Does the food Jo logged as eaten say **Added by Jo**?
* As **tester-helper**, look at **Suggestions you sent**. Does it say Sam added it?
* As **tester**, untick **Log food I ate** for Jo. On Jo's phone, try **Mark eaten** again. Jo should be told they can no longer
  do that.

### 12. Without a connection (5 minutes)

As **tester**, turn on airplane mode.

* Add a food. The top of the screen should say **Offline**, then how many entries wait to be sent.
* Turn airplane mode off. Do they go to the server? Does anything get lost or added twice?

### 13. Your data (2 minutes)

Open **Settings**.

* Find **Export my data**. Is it clear what you get?
* Is it clear where Sam's data is kept? Is there anything here that worries you about privacy?

## Questions for the end

Please answer these in your own words, with **Send feedback** or in a message. Short answers are fine.

1. Would you, or the person you care for, use this every day? Why or why not?
2. What was the most useful thing in it?
3. What was the most confusing thing?
4. Did anything look **wrong or unsafe** for someone with CKD? (Wrong numbers, bad suggestions, scary or missing warnings.)
5. What is missing that you would need? (A food, a feature, a way of entering things, a report.)
6. Who do you think this would help most: early-stage CKD, late stage, dialysis, caregivers, dietitians?
7. Anything else?

Thank you. Every note helps make this better for people living with kidney disease.
