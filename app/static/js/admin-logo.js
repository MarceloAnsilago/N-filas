const logoForm = document.getElementById('logo-form');
const logoPreview = document.getElementById('logo-previa');
const logoImage = document.getElementById('logo-imagem');
const defaultLogoNotice = document.getElementById('logo-padrao');
const savedLogo = logoImage.getAttribute('src');
let selectedLogo;

function updateLogoSize() {
  const { logo_largura, logo_altura, logo_esticar } = logoForm.elements;
  logoImage.style.width = document.getElementById('logo-largura-valor').value = `${logo_largura.value}%`;
  logoImage.style.height = document.getElementById('logo-altura-valor').value = `${logo_altura.value}%`;
  logoImage.style.objectFit = logo_esticar.checked ? 'fill' : 'contain';
}

logoForm.addEventListener('input', updateLogoSize);
logoForm.elements.logo.addEventListener('change', event => {
  if (selectedLogo) URL.revokeObjectURL(selectedLogo);
  const file = event.target.files[0];
  selectedLogo = file ? URL.createObjectURL(file) : null;
  const source = selectedLogo || savedLogo;
  if (source) logoImage.src = source;
  else logoImage.removeAttribute('src');
  logoPreview.hidden = !source;
  if (defaultLogoNotice) defaultLogoNotice.hidden = !!source;
});
