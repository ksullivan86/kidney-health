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

### 10. Plan Sam's meals as a family member (10 minutes)

On a second phone or a computer, open the same address and sign in as **tester-helper**. This is Jo, who helps Sam with meals.

* Go to **Settings → Care team**. Under **Care teams you are on**, you should see Sam, as a **Care helper**.
* Press **Plan meals** (or **Planning for** at the top of the **Plan** tab). Is it clear that you are changing Sam's plan, not
  your own? Add a food to tomorrow, then press **Back to my own plan**.
* Back on the first phone, as **tester**: open tomorrow on **Today**. Does the food say **Added by Jo**?
* As **tester**, open **Settings → Care team** and change Jo's **Role** to **Viewer**. On the second phone, can Jo still plan
  Sam's meals? (Jo should only be able to look.) Then change it back to **Care helper**.

### 11. Without a connection (5 minutes)

As **tester**, turn on airplane mode.

* Add a food. The top of the screen should say **Offline**, then how many entries wait to be sent.
* Turn airplane mode off. Do they go to the server? Does anything get lost or added twice?

### 12. Your data (2 minutes)

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
