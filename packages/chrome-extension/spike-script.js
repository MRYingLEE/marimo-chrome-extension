// Loaded by the seed notebook's `mo.Html` cell. The output element may be
// mounted after this script runs, so wait for it.
const timer = setInterval(() => {
  const element = document.getElementById("spike-html-script");
  if (element) {
    element.textContent = "external script ran";
    clearInterval(timer);
  }
}, 50);
