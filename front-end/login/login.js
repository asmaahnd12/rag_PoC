const loginButton = document.querySelector(".login-box button");


// Sélectionner le paragraphe pour afficher les erreurs
let errorMessage = document.querySelector(".error-message");


async function handleLogin() {
  const username = document
    .querySelector('.login-box input[type="text"]')
    .value.trim();


  const password = document
    .querySelector('.login-box input[type="password"]')
    .value.trim();


  if (username === "" || password === "") {
    errorMessage.textContent = "Veuillez remplir tous les champs !";
    errorMessage.style.display = "block";
    return;
  }


  try {
    const response = await fetch(API_ENDPOINTS.login, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });


    const data = await response.json();


    if (response.ok) {
      //  Stocker le token
      localStorage.setItem("access_token", data.access_token);


      //  Stocker username (utile pour avatar plus tard)
      localStorage.setItem("username", username);


      errorMessage.style.display = "none";


      //  Redirection vers la page chat
      window.location.href = "/chat";
    } else {
      errorMessage.textContent = data.detail || "Login failed";
      errorMessage.style.display = "block";
    }
  } catch (error) {
    errorMessage.textContent = "Erreur de connexion au serveur";
    errorMessage.style.display = "block";
  }
}


loginButton.addEventListener("click", handleLogin);


// Appuyer sur Entrée pour se connecter
document.addEventListener("keydown", function (event) {
  if (event.key === "Enter") {
    handleLogin();
  }
});
