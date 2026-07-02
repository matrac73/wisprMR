const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
document.documentElement.classList.add("js");

const copy = {
  fr: {
    navHow: "Fonctionnement",
    themeLabel: "Clair",
    eyebrow: "Local voice dictation",
    heroLine1: "Dictez.",
    heroLine2: "Relachez.",
    downloadWin: "Download",
    downloadMac: "Download",
    downloadMobile: "Download",
    holdShortcut: "hold <b>ctrl + space</b>",
    sampleText: "\"On se cale un point demain matin.\"",
    metricLocal: "local sur ordinateur",
    metricSpeed: "la vitesse d'ecriture",
    metricFree: "free + open source",
    platformWindows: "Windows detecte : le bouton telecharge l'assistant d'installation PC.",
    platformMac: "Mac detecte : le bouton telecharge le pack macOS a lancer en double-clic.",
    platformAndroid: "Android detecte : pour le comportement volume + ecoute + collage global, il faut une app native Android signee. Le package mobile n'est pas encore present dans ce repo.",
    platformIos: "iPhone detecte : iOS exige une app native signee pour ecouter en arriere-plan, reagir aux boutons physiques et coller dans une autre app. Le package iPhone n'est pas encore present dans ce repo.",
    platformMobile: "Mobile detecte : le site est pret pour servir le bon package mobile, mais l'app native n'est pas encore incluse.",
    nodePlatform: "OS",
    nodeMic: "Mic",
    nodeBoot: "Boot",
    nodeStt: "STT",
    nodePolish: "Polish",
    nodePaste: "Paste",
    coreLabel: "pipeline local",
    howEyebrow: "Fonctionnement",
    howTitle: "Ce qui se passe sous le capot.",
    howOneTitle: "Detection cross-platform",
    howOneBody: "Un seul bouton Download apparait. PC reçoit le setup Windows, Mac reçoit le pack macOS, mobile reçoit le parcours app native.",
    howTwoTitle: "Capture micro automatique",
    howTwoBody: "Maintenir le raccourci enregistre la voix via le micro systeme, sans choisir de device a chaque fois.",
    howThreeTitle: "Autostart propre",
    howThreeBody: "L'outil peut se lancer au demarrage de l'ordinateur et rester disponible en arriere-plan.",
    howFourTitle: "Transcription configurable",
    howFourBody: "La voix passe dans faster-whisper local. Le modele, la langue et le niveau de precision peuvent etre ajustes.",
    howFiveTitle: "Polishing separe",
    howFiveBody: "Un second modele peut nettoyer le brut : ponctuation, termes metier, phrases plus nettes.",
    howSixTitle: "Collage partout",
    howSixBody: "Le texte final est injecte dans l'app active : mail, meeting notes, navigateur, CRM ou document.",
  },
  en: {
    navHow: "How it works",
    themeLabel: "Light",
    eyebrow: "Local voice dictation",
    heroLine1: "Speak.",
    heroLine2: "Release.",
    downloadWin: "Download",
    downloadMac: "Download",
    downloadMobile: "Download",
    holdShortcut: "hold <b>ctrl + space</b>",
    sampleText: "\"Let's sync tomorrow morning.\"",
    metricLocal: "local on computer",
    metricSpeed: "writing speed",
    metricFree: "free + open source",
    platformWindows: "Windows detected: the button downloads the PC setup wizard.",
    platformMac: "Mac detected: the button downloads the macOS package to run by double-click.",
    platformAndroid: "Android detected: volume-button listening and global paste require a signed native Android app. The mobile package is not included in this repo yet.",
    platformIos: "iPhone detected: iOS requires a signed native app for background listening, physical buttons, and pasting into another app. The iPhone package is not included in this repo yet.",
    platformMobile: "Phone detected: the site is ready to serve the right mobile package, but the native app is not included yet.",
    nodePlatform: "OS",
    nodeMic: "Mic",
    nodeBoot: "Boot",
    nodeStt: "STT",
    nodePolish: "Polish",
    nodePaste: "Paste",
    coreLabel: "local pipeline",
    howEyebrow: "How it works",
    howTitle: "What happens under the hood.",
    howOneTitle: "Cross-platform detection",
    howOneBody: "One Download button appears. PC gets the Windows setup, Mac gets the macOS pack, mobile gets the native-app path.",
    howTwoTitle: "Automatic mic capture",
    howTwoBody: "Holding the shortcut records from the system microphone without selecting an input every time.",
    howThreeTitle: "Clean autostart",
    howThreeBody: "The tool can launch when the computer starts and stay available in the background.",
    howFourTitle: "Configurable transcription",
    howFourBody: "Voice runs through local faster-whisper. Model, language, and precision can be adjusted.",
    howFiveTitle: "Separate polishing",
    howFiveBody: "A second model can clean the raw text: punctuation, business vocabulary, sharper phrasing.",
    howSixTitle: "Paste anywhere",
    howSixBody: "The final text is injected into the active app: mail, meeting notes, browser, CRM, or document.",
  },
};

let currentTheme = localStorage.getItem("wispr-theme") || "dark";
let currentLang = localStorage.getItem("wispr-lang") || "fr";
let detectedOs = "windows";
let activeScrollyStep = 0;

function detectPlatform() {
  const userAgent = navigator.userAgent || "";
  const platform = navigator.platform || "";
  const touchMac = platform === "MacIntel" && navigator.maxTouchPoints > 1;
  const isAndroid = /Android/i.test(userAgent);
  const isIos = /iPhone|iPad|iPod/i.test(userAgent) || touchMac;
  const isMobile = isAndroid || isIos || (/Mobile/i.test(userAgent) && window.innerWidth < 980);
  const isMac = /Mac/i.test(platform) || /Macintosh/i.test(userAgent);
  const isWindows = /Win/i.test(platform) || /Windows/i.test(userAgent);

  if (isAndroid) return { platform: "mobile", os: "android" };
  if (isIos) return { platform: "mobile", os: "ios" };
  if (isMobile) return { platform: "mobile", os: "mobile" };
  if (isMac) return { platform: "mac", os: "mac" };
  if (isWindows) return { platform: "windows", os: "windows" };
  return { platform: "windows", os: "windows" };
}

function platformMessageKey() {
  if (detectedOs === "android") return "platformAndroid";
  if (detectedOs === "ios") return "platformIos";
  if (detectedOs === "mobile") return "platformMobile";
  if (detectedOs === "mac") return "platformMac";
  return "platformWindows";
}

function applyPlatform() {
  const detected = detectPlatform();
  detectedOs = detected.os;
  document.documentElement.dataset.platform = detected.platform;
  document.documentElement.dataset.os = detected.os;
  updatePlatformMessages();
}

function updatePlatformMessages() {
  const message = copy[currentLang][platformMessageKey()];
  for (const node of document.querySelectorAll("[data-platform-message]")) {
    node.textContent = message;
  }
}

function applyLanguage(lang) {
  currentLang = copy[lang] ? lang : "fr";
  localStorage.setItem("wispr-lang", currentLang);
  document.documentElement.lang = currentLang;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    const key = node.dataset.i18n;
    if (copy[currentLang][key]) {
      node.innerHTML = copy[currentLang][key];
    }
  }
  for (const button of document.querySelectorAll("[data-lang]")) {
    button.classList.toggle("is-active", button.dataset.lang === currentLang);
  }
  for (const step of document.querySelectorAll(".scrolly-step")) {
    step.dataset.detail = step.dataset[currentLang === "fr" ? "detailFr" : "detailEn"] || "";
  }
  updatePlatformMessages();
}

function applyTheme(theme) {
  currentTheme = theme === "light" ? "light" : "dark";
  localStorage.setItem("wispr-theme", currentTheme);
  document.documentElement.dataset.theme = currentTheme;
  const toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    const label = currentTheme === "dark"
      ? (currentLang === "fr" ? "Clair" : "Light")
      : (currentLang === "fr" ? "Sombre" : "Dark");
    toggle.textContent = label;
  }
}

document.querySelectorAll("[data-lang]").forEach((button) => {
  button.addEventListener("click", () => {
    applyLanguage(button.dataset.lang);
    applyTheme(currentTheme);
  });
});

document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
  applyTheme(currentTheme === "dark" ? "light" : "dark");
});

document.querySelectorAll("[data-mobile-native-info]").forEach((button) => {
  button.addEventListener("click", () => {
    const note = document.querySelector("[data-platform-message]");
    note?.classList.add("is-highlighted");
    note?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => note?.classList.remove("is-highlighted"), 1500);
  });
});

const revealObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("in-view");
        revealObserver.unobserve(entry.target);
      }
    }
  },
  { threshold: 0.16 }
);

document.querySelectorAll(".reveal").forEach((node) => revealObserver.observe(node));

for (const [index, bar] of document.querySelectorAll(".wave i").entries()) {
  bar.style.setProperty("--i", index);
}

const canvas = document.getElementById("pixel-field");
const ctx = canvas.getContext("2d", { alpha: true });
let width = 0;
let height = 0;
let dpr = 1;
let pixels = [];
let pointer = { x: -9999, y: -9999 };
let scrollInfluence = 0;

function resize() {
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = window.innerWidth;
  height = window.innerHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  seedPixels();
}

function seedPixels() {
  const spacing = width < 760 ? 34 : 42;
  pixels = [];
  for (let y = spacing * 0.6; y < height; y += spacing) {
    for (let x = spacing * 0.6; x < width; x += spacing) {
      if (Math.random() > 0.62) {
        pixels.push({
          x,
          y,
          base: Math.random() * 0.42 + 0.08,
          phase: Math.random() * Math.PI * 2,
          size: Math.random() > 0.82 ? 3 : 2,
        });
      }
    }
  }
}

function pixelColor(alpha) {
  return currentTheme === "light"
    ? `rgba(7,7,7,${alpha})`
    : `rgba(247,247,242,${alpha})`;
}

function draw(time = 0) {
  ctx.clearRect(0, 0, width, height);
  const t = time * 0.001;
  for (const pixel of pixels) {
    const dx = pixel.x - pointer.x;
    const dy = pixel.y - pointer.y;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const pull = Math.max(0, 1 - distance / 180);
    const shimmer = Math.sin(t + pixel.phase + scrollInfluence * 4) * 0.16;
    const alpha = Math.max(0, Math.min(0.8, pixel.base + shimmer + pull * 0.55));
    const size = pixel.size + pull * 3;
    ctx.fillStyle = pixelColor(alpha);
    ctx.fillRect(pixel.x - size / 2, pixel.y - size / 2, size, size);
  }
  if (!prefersReducedMotion) requestAnimationFrame(draw);
}

function onScroll() {
  const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  scrollInfluence = window.scrollY / max;
  updateScrolly();
}

function updateScrolly() {
  const scrolly = document.querySelector("[data-scrolly]");
  if (!scrolly) return;

  const rect = scrolly.getBoundingClientRect();
  const total = Math.max(1, rect.height - window.innerHeight);
  const progress = Math.max(0, Math.min(1, -rect.top / total));
  const steps = [...document.querySelectorAll(".scrolly-step")];
  let nextStep = activeScrollyStep;
  let closestDistance = Number.POSITIVE_INFINITY;

  steps.forEach((step, index) => {
    const stepRect = step.getBoundingClientRect();
    const distance = Math.abs(stepRect.top + stepRect.height * 0.5 - window.innerHeight * 0.52);
    if (distance < closestDistance) {
      closestDistance = distance;
      nextStep = index;
    }
  });

  activeScrollyStep = nextStep;
  scrolly.style.setProperty("--scrolly-progress", progress.toFixed(3));
  scrolly.style.setProperty("--active-step", String(activeScrollyStep));

  steps.forEach((step, index) => {
    step.classList.toggle("is-active", index === activeScrollyStep);
  });
  document.querySelectorAll("[data-step-node]").forEach((node) => {
    node.classList.toggle("is-active", Number(node.dataset.stepNode) === activeScrollyStep);
  });
}

window.addEventListener("resize", resize, { passive: true });
window.addEventListener("scroll", onScroll, { passive: true });
window.addEventListener("pointermove", (event) => {
  pointer = { x: event.clientX, y: event.clientY };
});
window.addEventListener("pointerleave", () => {
  pointer = { x: -9999, y: -9999 };
});

applyPlatform();
applyLanguage(currentLang);
applyTheme(currentTheme);
resize();
onScroll();
draw();

if (prefersReducedMotion) {
  draw(0);
}
