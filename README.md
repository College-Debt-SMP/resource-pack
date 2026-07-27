# College Debt SMP Global Resource Pack

This repository contains the resource pack that will be automatically download upon each server join. They include the resources for the following datapacks and their respective version:
- College Debt SMP Custom Paintings – Continue reading for submission instructions
- [Dungeons and Taverns (DnT)](https://modrinth.com/datapack/dungeons-and-taverns) – 5.3.0
- [Elytra Trims](https://modrinth.com/mod/elytra-trims) – 4.8.3
- [Portfolio](https://modrinth.com/datapack/portfolio) – 1.5.5

## Submitting custom painting(s)

Players can submit custom paintings to be added to the server-wide resource pack and datapack.

### Step 1: Create your Custom Painting Zip
1. Go to [mc-tools.net](https://mc-tools.net/paintings).
2. Upload the images you want to turn into paintings. Adjust the settings to your own preference.
3. Download the generated resource pack `.zip` file. Ensure the zip contains the `mctools.json` file and the painting PNG textures.

### Step 2: Submit via GitHub Issues
1. Open a **New Issue** in this repository.
2. Attach your downloaded `.zip` file directly into the issue description box.
3. Add the **`painting-submission`** label to your issue.
4. The automated workflow will run automatically to:
   - Validate your `.zip` file.
   - Extract the painting textures and generate the corresponding datapack entries.
   - Automatically commit the assets, publish a new release, and close the issue with a confirmation message.

### Step 3 (optional): Managing Existing Submissions

You can manage or modify your submission directly from the closed issue thread:

**Show available commands:**
- Reply with the exact comment: `help`

**List paintings in this submission:**
- Reply with the exact comment: `list`
- The bot will reply with each painting's slug, current title, and dimensions.

**Rename a painting title:**
- If the submission has **one** painting, reply with: `rename Tortellini's Sandwich`
- You can always target a specific painting by slug: `rename tortellini_comfort Tortellini's Sandwich`
- If the submission has **multiple** paintings, the slug is required. If you omit it or use an unknown slug, the bot will list the available slugs.
- This only changes the display title used in the stonecutter UI. The `cdsmp:` resource ID stays the same.

**Undo / Revert a Submission:**
- Reply to your closed submission issue with the exact comment: `undo`
- The bot will remove all textures and datapack entries associated with that issue.
  
**Replace / Update a Submission:**
- Reply to your closed submission issue with a comment attaching a **new `.zip` file**.
- The bot will automatically revert your old submission and process the new zip file.

> **Note:** If you have already undone a submission and want to submit again later, please open a **new issue** rather than commenting on the old one.

For more information, refer to the server's documentation.