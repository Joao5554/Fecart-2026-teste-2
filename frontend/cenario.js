/* Cenário animado do Fecart 2026.

   Duas animações de fundo, as duas em canvas 2D puro, sem nenhuma biblioteca:

     Cenario.globo(canvas)  o globo que gira na tela de abertura
     Cenario.clima(canvas)  o vento e os ciclones por trás dos mapas

   O projeto inteiro roda offline, sem CDN e sem chave de API. Uma biblioteca
   3D custaria centenas de KB baixados de fora só para o plano de fundo, então
   a esfera é projetada à mão — ortográfica, a mesma projeção de um globo
   visto de muito longe — e o vento é um campo de partículas. É a mesma
   escolha que o resto do projeto já fazia ao desenhar os mapas sem D3.

   Quem pediu "menos animação" no sistema operacional recebe um quadro parado
   em vez do laço: as duas animações respeitam prefers-reduced-motion. */

const Cenario = (() => {
  "use strict";

  const PARADO = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const GRAU = Math.PI / 180;

  /* Ajusta o canvas à sua caixa na tela, na densidade real do monitor.
     Sem isso o desenho sai borrado em tela de alta densidade. */
  function dimensionar(canvas) {
    const densidade = Math.min(devicePixelRatio || 1, 2);
    const largura = canvas.clientWidth || canvas.offsetWidth || 1;
    const altura = canvas.clientHeight || canvas.offsetHeight || 1;
    canvas.width = Math.round(largura * densidade);
    canvas.height = Math.round(altura * densidade);
    const contexto = canvas.getContext("2d");
    contexto.setTransform(densidade, 0, 0, densidade, 0, 0);
    return { contexto, largura, altura };
  }

  /* Laço de animação com pausa automática.

     A aba escondida e o palco inativo param o desenho: um globo girando atrás
     de uma tela que ninguém está vendo gasta bateria e nada mais. */
  function laco(desenhar) {
    let pedido = null;
    let ativo = true;
    let inicio = performance.now();

    const quadro = (agora) => {
      pedido = requestAnimationFrame(quadro);
      if (!ativo || document.hidden) return;
      desenhar((agora - inicio) / 1000);
    };

    pedido = requestAnimationFrame(quadro);

    return {
      pausar() { ativo = false; },
      seguir() { ativo = true; },
      parar() { if (pedido) cancelAnimationFrame(pedido); pedido = null; },
    };
  }

  // -------------------------------------------------------------------------
  // Globo
  // -------------------------------------------------------------------------

  /* O contorno do país sai de dados/preparar_silhueta.py, que reduz os 5.570
     municípios da malha do IBGE a algumas centenas de pontos. Enquanto o
     arquivo não chega, o globo desenha os meridianos e o mar — ele nunca fica
     esperando, porque é a primeira coisa que a pessoa vê. */
  let promessaSilhueta = null;

  function carregarSilhueta() {
    if (!promessaSilhueta) {
      promessaSilhueta = fetch("silhueta_brasil.json")
        .then((r) => (r.ok ? r.json() : { aneis: [] }))
        .then((d) => d.aneis || [])
        .catch(() => []);
    }
    return promessaSilhueta;
  }

  function globo(canvas, opcoes = {}) {
    const VELOCIDADE = opcoes.velocidade ?? 7;   // graus por segundo
    const INCLINACAO = -12 * GRAU;               // o Brasil um pouco abaixo do eixo
    let giro = -104 * GRAU;                      // começa com o país fora de vista

    let aneis = [];
    let marcadores = [];
    carregarSilhueta().then((a) => { aneis = a; });

    // As capitais viram pontos que pulsam sobre o país. Vêm da API, que é
    // local; se ela ainda não subiu, o globo simplesmente não tem pontos.
    fetch("/mapa/capitais")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) marcadores = d.capitais || []; })
      .catch(() => { /* sem pontos, o globo continua igual */ });

    const estrelas = Array.from({ length: 220 }, () => ({
      x: Math.random(), y: Math.random(),
      raio: Math.random() * 1.1 + 0.3,
      fase: Math.random() * Math.PI * 2,
      brilho: Math.random() * 0.5 + 0.25,
    }));

    /* Projeção ortográfica: a esfera vista do infinito.

       `cosseno` é o cosseno da distância angular até o centro do disco. Ele é
       negativo exatamente nos pontos que estão do outro lado do planeta — é
       por ele que se sabe o que esconder. */
    function projetar(lon, lat, centroX, centroY, raio) {
      const dl = lon * GRAU - giro;
      const fi = lat * GRAU;
      const senoFi = Math.sin(fi), cossenoFi = Math.cos(fi);
      const senoIncl = Math.sin(INCLINACAO), cossenoIncl = Math.cos(INCLINACAO);
      const cosseno = senoIncl * senoFi + cossenoIncl * cossenoFi * Math.cos(dl);
      return {
        x: centroX + raio * cossenoFi * Math.sin(dl),
        y: centroY - raio * (cossenoIncl * senoFi - senoIncl * cossenoFi * Math.cos(dl)),
        visivel: cosseno >= 0,
        cosseno,
      };
    }

    /* Desenha um anel de coordenadas quebrando-o onde ele passa por trás do
       globo. Sem essa quebra, o traço cortaria o disco em linha reta de um
       lado ao outro quando o país começasse a sumir na borda. */
    function tracarAnel(contexto, anel, centroX, centroY, raio, fechar) {
      let desenhando = false;
      let algumTraco = false;
      contexto.beginPath();
      for (const [lon, lat] of anel) {
        const p = projetar(lon, lat, centroX, centroY, raio);
        if (!p.visivel) { desenhando = false; continue; }
        if (!desenhando) { contexto.moveTo(p.x, p.y); desenhando = true; algumTraco = true; }
        else contexto.lineTo(p.x, p.y);
      }
      if (fechar && algumTraco) contexto.closePath();
      return algumTraco;
    }

    function meridianosEParalelos(contexto, centroX, centroY, raio) {
      contexto.lineWidth = 1;
      contexto.strokeStyle = "rgba(125, 211, 252, 0.16)";

      for (let lon = -180; lon < 180; lon += 20) {
        const anel = [];
        for (let lat = -90; lat <= 90; lat += 4) anel.push([lon, lat]);
        tracarAnel(contexto, anel, centroX, centroY, raio, false);
        contexto.stroke();
      }
      for (let lat = -60; lat <= 60; lat += 20) {
        const anel = [];
        for (let lon = -180; lon <= 180; lon += 4) anel.push([lon, lat]);
        tracarAnel(contexto, anel, centroX, centroY, raio, false);
        contexto.stroke();
      }

      // A linha do equador é a única com peso próprio: ela dá a inclinação do
      // eixo num relance, e o Brasil é cortado por ela.
      contexto.strokeStyle = "rgba(125, 211, 252, 0.34)";
      const equador = [];
      for (let lon = -180; lon <= 180; lon += 3) equador.push([lon, 0]);
      tracarAnel(contexto, equador, centroX, centroY, raio, false);
      contexto.stroke();
    }

    function esfera(contexto, centroX, centroY, raio) {
      // Atmosfera: um halo que vaza para fora do disco. É o que separa o
      // planeta do fundo preto sem precisar de contorno duro.
      const halo = contexto.createRadialGradient(
        centroX, centroY, raio * 0.92, centroX, centroY, raio * 1.28);
      halo.addColorStop(0, "rgba(56, 132, 255, 0.34)");
      halo.addColorStop(0.55, "rgba(56, 132, 255, 0.10)");
      halo.addColorStop(1, "rgba(56, 132, 255, 0)");
      contexto.fillStyle = halo;
      contexto.beginPath();
      contexto.arc(centroX, centroY, raio * 1.28, 0, Math.PI * 2);
      contexto.fill();

      // O oceano, iluminado de cima à esquerda: o degradê deslocado é o que
      // faz um círculo chapado parecer uma bola.
      const oceano = contexto.createRadialGradient(
        centroX - raio * 0.35, centroY - raio * 0.42, raio * 0.08,
        centroX, centroY, raio * 1.05);
      oceano.addColorStop(0, "#1b3f7a");
      oceano.addColorStop(0.45, "#122a52");
      oceano.addColorStop(0.82, "#0a1730");
      oceano.addColorStop(1, "#060d1c");
      contexto.fillStyle = oceano;
      contexto.beginPath();
      contexto.arc(centroX, centroY, raio, 0, Math.PI * 2);
      contexto.fill();
    }

    function pais(contexto, centroX, centroY, raio) {
      if (!aneis.length) return;
      contexto.save();
      contexto.beginPath();
      contexto.arc(centroX, centroY, raio, 0, Math.PI * 2);
      contexto.clip();

      for (const anel of aneis) {
        if (!tracarAnel(contexto, anel, centroX, centroY, raio, true)) continue;
        contexto.fillStyle = "rgba(64, 132, 246, 0.62)";
        contexto.fill();
        contexto.lineWidth = 1.4;
        contexto.strokeStyle = "rgba(147, 213, 255, 0.85)";
        contexto.stroke();
      }
      contexto.restore();
    }

    function pontos(contexto, centroX, centroY, raio, tempo) {
      contexto.save();
      marcadores.forEach((capital, i) => {
        const p = projetar(capital.lon, capital.lat, centroX, centroY, raio);
        if (!p.visivel) return;

        // Perto da borda o ponto está quase de perfil: some junto com a curva
        // da esfera, em vez de piscar ao cruzar o limite.
        const forca = Math.min(p.cosseno * 2.2, 1);
        const pulso = (tempo * 0.55 + i * 0.37) % 1;

        contexto.globalAlpha = forca * (1 - pulso) * 0.55;
        contexto.strokeStyle = "#67e8f9";
        contexto.lineWidth = 1.2;
        contexto.beginPath();
        contexto.arc(p.x, p.y, 2 + pulso * 13, 0, Math.PI * 2);
        contexto.stroke();

        contexto.globalAlpha = forca;
        contexto.fillStyle = "#a5f3fc";
        contexto.beginPath();
        contexto.arc(p.x, p.y, 1.7, 0, Math.PI * 2);
        contexto.fill();
      });
      contexto.restore();
    }

    function ceu(contexto, largura, altura, tempo) {
      contexto.fillStyle = "#04070f";
      contexto.fillRect(0, 0, largura, altura);
      for (const e of estrelas) {
        const cintila = 0.65 + 0.35 * Math.sin(tempo * 1.4 + e.fase);
        contexto.globalAlpha = e.brilho * cintila;
        contexto.fillStyle = "#dbeafe";
        contexto.beginPath();
        contexto.arc(e.x * largura, e.y * altura, e.raio, 0, Math.PI * 2);
        contexto.fill();
      }
      contexto.globalAlpha = 1;
    }

    let anterior = 0;

    function desenhar(tempo) {
      const { contexto, largura, altura } = dimensionar(canvas);

      if (!PARADO) {
        const passo = anterior ? Math.min(tempo - anterior, 0.1) : 0;
        giro += VELOCIDADE * GRAU * passo;
      }
      anterior = tempo;

      const centroX = largura * (opcoes.centroX ?? 0.5);
      const centroY = altura * (opcoes.centroY ?? 0.5);
      const raio = Math.min(largura, altura) * (opcoes.raio ?? 0.34);

      ceu(contexto, largura, altura, tempo);
      esfera(contexto, centroX, centroY, raio);
      meridianosEParalelos(contexto, centroX, centroY, raio);
      pais(contexto, centroX, centroY, raio);
      pontos(contexto, centroX, centroY, raio, tempo);
    }

    if (PARADO) {
      // Um quadro só, com o Brasil de frente. Os dados chegam por fetch, então
      // vale redesenhar quando eles chegarem — mas sem laço nenhum.
      giro = -53 * GRAU;
      const repintar = () => desenhar(0);
      repintar();
      carregarSilhueta().then(repintar);
      addEventListener("resize", repintar);
      return { pausar() {}, seguir() {}, parar() { removeEventListener("resize", repintar); } };
    }

    return laco(desenhar);
  }

  // -------------------------------------------------------------------------
  // Vento e ciclones
  // -------------------------------------------------------------------------

  /* Campo de vento por partículas: milhares de pontos seguem um campo de
     velocidade e deixam rastro. É como se desenham mapas de vento de verdade,
     e sai muito mais barato que qualquer malha 3D.

     Sobre o campo largo somam-se alguns ciclones. Eles giram no sentido
     horário porque estamos no hemisfério sul — no norte, a força de Coriolis
     os faz girar ao contrário. */
  function clima(canvas, opcoes = {}) {
    const QUANTIDADE = opcoes.particulas ?? 900;
    const VIDA = 130;             // quadros até a partícula renascer
    const VELOCIDADE = 1.5;

    let largura = 1, altura = 1;
    let particulas = [];
    let ciclones = [];

    function semear() {
      particulas = Array.from({ length: QUANTIDADE }, () => ({
        x: Math.random() * largura,
        y: Math.random() * altura,
        idade: Math.random() * VIDA,
      }));

      // Três ciclones, em posições e tamanhos diferentes, para o fundo não
      // ficar com um padrão que se repete e denuncia o truque.
      ciclones = [
        { x: 0.24, y: 0.34, raio: 0.34, forca: 2.6, deriva: 0.021, fase: 0 },
        { x: 0.72, y: 0.62, raio: 0.28, forca: 2.1, deriva: 0.016, fase: 2.1 },
        { x: 0.52, y: 0.16, raio: 0.22, forca: 1.5, deriva: 0.027, fase: 4.2 },
      ];
    }

    function moverCiclones(tempo) {
      const escala = Math.min(largura, altura);
      for (const c of ciclones) {
        c.px = (c.x + Math.sin(tempo * c.deriva + c.fase) * 0.06) * largura;
        c.py = (c.y + Math.cos(tempo * c.deriva * 1.3 + c.fase) * 0.05) * altura;
        c.praio = c.raio * escala;
      }
    }

    function vento(x, y, tempo) {
      // Sopros largos, sobrepostos em escalas diferentes: duas senoides já
      // bastam para o movimento não parecer uma esteira reta.
      let vx = Math.sin(y * 0.0060 + tempo * 0.16) * 1.05
             + Math.cos((x + y) * 0.0034 - tempo * 0.11) * 0.62;
      let vy = Math.cos(x * 0.0052 - tempo * 0.13) * 0.60
             + Math.sin((x - y) * 0.0041 + tempo * 0.09) * 0.42;

      for (const c of ciclones) {
        const dx = x - c.px, dy = y - c.py;
        const distancia = Math.hypot(dx, dy) + 1;
        if (distancia > c.praio) continue;

        // A força cai até zerar na borda: assim o ciclone se dissolve no vento
        // de fundo em vez de terminar num círculo visível.
        const forca = c.forca * (1 - distancia / c.praio) ** 1.5;
        vx += (dy / distancia) * forca - (dx / distancia) * forca * 0.22;
        vy += (-dx / distancia) * forca - (dy / distancia) * forca * 0.22;
      }
      return [vx, vy];
    }

    function olhos(contexto, tempo) {
      for (const c of ciclones) {
        const halo = contexto.createRadialGradient(
          c.px, c.py, 0, c.px, c.py, c.praio);
        halo.addColorStop(0, "rgba(103, 232, 249, 0.11)");
        halo.addColorStop(0.35, "rgba(59, 130, 246, 0.05)");
        halo.addColorStop(1, "rgba(59, 130, 246, 0)");
        contexto.fillStyle = halo;
        contexto.beginPath();
        contexto.arc(c.px, c.py, c.praio, 0, Math.PI * 2);
        contexto.fill();

        // Braços em espiral logarítmica, girando: é o desenho que faz o olho
        // ler "ciclone" e não "mancha de luz".
        contexto.strokeStyle = "rgba(147, 213, 255, 0.13)";
        contexto.lineWidth = 1.1;
        for (let braco = 0; braco < 3; braco++) {
          contexto.beginPath();
          const giro = tempo * 0.28 + (braco * Math.PI * 2) / 3;
          for (let t = 0.08; t < 1; t += 0.03) {
            const angulo = giro - t * 5.2;
            const r = t * c.praio * 0.82;
            const x = c.px + Math.cos(angulo) * r;
            const y = c.py + Math.sin(angulo) * r;
            if (t < 0.11) contexto.moveTo(x, y); else contexto.lineTo(x, y);
          }
          contexto.stroke();
        }
      }
    }

    let tamanhoAnterior = "";

    function desenhar(tempo) {
      const medida = `${canvas.clientWidth}x${canvas.clientHeight}`;
      if (medida !== tamanhoAnterior) {
        const dimensoes = dimensionar(canvas);
        largura = dimensoes.largura;
        altura = dimensoes.altura;
        tamanhoAnterior = medida;
        semear();
        dimensoes.contexto.fillStyle = "#070d1b";
        dimensoes.contexto.fillRect(0, 0, largura, altura);
      }

      const contexto = canvas.getContext("2d");
      const densidade = Math.min(devicePixelRatio || 1, 2);
      contexto.setTransform(densidade, 0, 0, densidade, 0, 0);

      // Em vez de limpar, cobre-se o quadro anterior com uma camada quase
      // transparente. O que já estava desenhado desbota aos poucos, e é
      // exatamente isso que vira o rastro das partículas.
      contexto.fillStyle = "rgba(7, 13, 27, 0.14)";
      contexto.fillRect(0, 0, largura, altura);

      moverCiclones(tempo);
      olhos(contexto, tempo);

      contexto.lineWidth = 1.05;
      contexto.strokeStyle = "rgba(125, 200, 255, 0.30)";
      contexto.beginPath();

      for (const p of particulas) {
        const [vx, vy] = vento(p.x, p.y, tempo);
        const x = p.x + vx * VELOCIDADE;
        const y = p.y + vy * VELOCIDADE;

        contexto.moveTo(p.x, p.y);
        contexto.lineTo(x, y);

        p.x = x;
        p.y = y;
        p.idade += 1;

        // Renasce ao envelhecer ou ao sair da tela. A idade limitada evita que
        // todas as partículas acabem presas nos mesmos ciclones, deixando o
        // resto do fundo vazio.
        if (p.idade > VIDA || x < 0 || x > largura || y < 0 || y > altura) {
          p.x = Math.random() * largura;
          p.y = Math.random() * altura;
          p.idade = 0;
        }
      }
      contexto.stroke();
    }

    if (PARADO) {
      const quadroUnico = () => {
        const dimensoes = dimensionar(canvas);
        largura = dimensoes.largura;
        altura = dimensoes.altura;
        semear();
        moverCiclones(0);
        dimensoes.contexto.fillStyle = "#070d1b";
        dimensoes.contexto.fillRect(0, 0, largura, altura);
        olhos(dimensoes.contexto, 0);
        // Alguns passos sem animar deixam um rastro estático, para a tela não
        // ficar só com os halos e nenhum sinal de vento.
        for (let i = 0; i < 60; i++) desenhar(0);
      };
      quadroUnico();
      addEventListener("resize", quadroUnico);
      return { pausar() {}, seguir() {}, parar() { removeEventListener("resize", quadroUnico); } };
    }

    return laco(desenhar);
  }

  return { globo, clima, reduzido: PARADO };
})();
