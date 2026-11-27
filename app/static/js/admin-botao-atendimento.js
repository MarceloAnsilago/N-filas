document.querySelectorAll(".service-editor").forEach((editor) => {
  const preview = editor.querySelector(".ticket-button");
  editor.querySelectorAll("input[type=color]").forEach((input) => {
    input.addEventListener("input", () => {
      const property = `--botao-${input.name}`;
      if (input.value === input.dataset.defaultColor) {
        preview.style.removeProperty(property);
      } else {
        preview.style.setProperty(property, input.value);
      }
    });
  });
});
