import fs from "node:fs";
import path from "node:path";

const root = path.resolve("docs-site");
const docsPath = path.join(root, "docs.json");
const docs = JSON.parse(fs.readFileSync(docsPath, "utf8"));
const currentLanguages = docs.navigation.languages;
const ruSource = currentLanguages.find((language) => language.language === "ru");
const enSource = currentLanguages.find((language) => language.language === "en");

if (!ruSource || !enSource) {
  throw new Error("docs-site/docs.json must already contain ru and en languages.");
}

const ruGroups = ruSource.groups.map((group) => ({
  group: group.group,
  pages: group.pages.map((page) => `ru/${page.replace(/^ru\//, "")}`),
}));

const enGroups = enSource.groups.map((group) => ({
  group: group.group,
  pages: group.pages.map((page) => `en/${page.replace(/^en\//, "")}`),
}));

for (const group of ruSource.groups) {
  for (const page of group.pages) {
    const pagePath = page.replace(/^ru\//, "");
    const source = path.join(root, `${pagePath}.mdx`);
    const target = path.join(root, "ru", `${pagePath}.mdx`);
    if (!fs.existsSync(source)) {
      throw new Error(`Missing Russian source page: ${source}`);
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(source, target);
  }
}

docs.navigation.languages = [
  { language: "en", default: true, groups: enGroups },
  { language: "ru", groups: ruGroups },
];

fs.writeFileSync(docsPath, `${JSON.stringify(docs, null, 2)}\n`, "utf8");
console.log("Synced docs-site language navigation to en/ru.");
