/* Camada de vento do Fecart 2026.

   Desenha, sobre o mapa, para onde o vento predominante sopra em cada mês —
   do jeito que mapas de vento de verdade fazem: partículas seguindo o campo e
   deixando rastro. Sem biblioteca nenhuma, como o resto do projeto.

   O dado vem de /clima/vento: uma medição por estação do INMET, com as
   componentes `u` (para leste) e `v` (para norte) em m/s. Entre as estações o
   valor é interpolado — é o mesmo que a camada de chuva faz, e pela mesma
   razão: só ~600 pontos do país têm medição, e o resto é estimativa
   declarada como tal.

   Dois espaços, e por que isso importa
   ------------------------------------
   As partículas vivem em coordenadas do MAPA, as mesmas do SVG: é lá que o
   campo de vento existe, e assim a física não muda quando a câmera se mexe.
   O desenho acontece em pixels de TELA, e a conversão é feita a cada traço.

   A alternativa — um canvas em coordenadas de mapa, dentro do elemento que a
   câmera amplia — foi o que este arquivo fazia antes, e não tem conserto: um
   bitmap de 1000x820 esticado a 2x ou 5x é borrão, e pedir linha mais fina
   para compensar só produz linha mais fraca, porque abaixo de um pixel do
   buffer não existe traço, existe cinza. Desenhando em espaço de tela, o
   traço tem um pixel de verdade em qualquer aproximação.

   Por que interpolar u e v, e não a direção
   -----------------------------------------
   Pela mesma razão que a média mensal é vetorial: ângulo não se interpola.
   Entre uma estação a 350° e outra a 10°, a média dos ângulos aponta para o
   sul. Interpolando as componentes, o resultado aponta para o norte, que é o
   que as duas estações estão dizendo.

   Sobre a velocidade da animação
   ------------------------------
   Ela é ilustrativa, não literal. Na escala do mapa, o vento real levaria
   horas para cruzar um estado, e a tela pareceria parada. Quem carrega a
   magnitude de verdade é a COR da partícula, que segue a escala em m/s
   devolvida pela API e aparece na legenda.

   O que faz esta camada ser barata
   --------------------------------
   Tudo o que é caro acontece UMA vez, ao ligar a camada, e vira tabela: o
   campo interpolado, e o contorno do mapa. O contorno tem ~145 mil comandos
   de caminho; usá-lo como `clip` a cada quadro custava ao rasterizador
   percorrer tudo isso 60 vezes por segundo. Aqui ele é rasterizado uma vez
   num mapa de bits, e o teste "isto é terra?" vira uma consulta de índice.

   O laço roda a 30 quadros por segundo, e não a 60: num campo de vento a
   diferença não se vê, e é metade do trabalho. */

const Vento = (() => {
  "use strict";

  const PARADO = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const COLUNAS_GRADE = 110;   // resolução do campo interpolado
  const RAIO_GRAUS = 4.5;      // além disso, nenhuma estação influencia
  const POTENCIA_IDW = 2.2;

  // O recorte de terra é rasterizado mais fino que o campo: o vento varia
  // devagar no espaço e uma grade grossa basta para ele, mas a linha da costa
  // numa grade grossa vira escada visível quando a câmera aproxima.
  const FINURA_MASCARA = 4;

  const PARTICULAS_POR_MILHAO = 5200;  // por milhão de pixels de tela
  const MAX_PARTICULAS = 2600;
  const VIDA = 90;             // quadros até a partícula renascer
  const VELOCIDADE_VISUAL = 1.6;
  const ESPESSURA = 1.15;      // pixels de tela
  const OPACIDADE = 0.9;
  // Quanto do rastro some a cada quadro. 0,08 guarda cerca de doze quadros de
  // cauda.
  //
  // É este número, e não a grossura, que decide se o desenho lê como TRAÇO ou
  // como PONTO. O que o olho vê é a razão entre o comprimento da cauda e a
  // largura da linha: com cauda curta, um vento fraco anda menos por quadro do
  // que a própria espessura da linha, e a ponta arredondada fecha um pingo.
  const APAGAMENTO = 0.08;

  const QUADROS_POR_SEGUNDO = 30;
  const INTERVALO = 1000 / QUADROS_POR_SEGUNDO;

  /* Agrupa as estações em baldes do tamanho do raio de influência.

     Sem isto, montar o campo compara cada uma das ~10 mil células com cada
     uma das ~650 estações. Com os baldes, cada célula só olha os 9 baldes à
     sua volta — nenhuma estação fora deles pode estar dentro do raio. */
  function agrupar(pontos, raio) {
    const baldes = new Map();
    for (const ponto of pontos) {
      const chave = `${Math.floor(ponto.x / raio)},${Math.floor(ponto.y / raio)}`;
      const balde = baldes.get(chave);
      if (balde) balde.push(ponto); else baldes.set(chave, [ponto]);
    }
    return baldes;
  }

  /* Rasteriza o contorno do mapa num mapa de bits de terra.

     É o que substitui o `clip` por quadro: preencher o caminho uma vez custa
     o mesmo que um recorte, e depois saber se um ponto é terra vira um índice
     de vetor. */
  function assarMascara(mascara, projecao, colunas, linhas) {
    if (!mascara) return null;

    const largura = colunas * FINURA_MASCARA;
    const altura = linhas * FINURA_MASCARA;

    const tela = document.createElement("canvas");
    tela.width = largura;
    tela.height = altura;

    const pincel = tela.getContext("2d", { willReadFrequently: true });
    pincel.scale(largura / projecao.largura, altura / projecao.altura);
    pincel.fillStyle = "#fff";
    try {
      pincel.fill(mascara);
    } catch (erro) {
      return null;   // sem recorte, a camada desenha em toda a área com dado
    }

    const pixels = pincel.getImageData(0, 0, largura, altura).data;
    const terra = new Uint8Array(largura * altura);
    for (let i = 0; i < terra.length; i++) {
      terra[i] = pixels[i * 4 + 3] > 8 ? 1 : 0;
    }

    return {
      terra, largura, altura,
      escalaX: largura / projecao.largura,
      escalaY: altura / projecao.altura,
    };
  }

  /* Interpola u e v numa grade, a partir das estações. */
  function montarCampo(projecao, estacoes, mascara) {
    const colunas = COLUNAS_GRADE;
    const linhas = Math.max(
      2, Math.round(colunas * projecao.altura / projecao.largura)
    );

    const u = new Float32Array(colunas * linhas);
    const v = new Float32Array(colunas * linhas);
    const forca = new Float32Array(colunas * linhas);
    const temDado = new Uint8Array(colunas * linhas);

    const pontos = estacoes.map((e) => ({
      x: projecao.px(e.lon),
      y: projecao.py(e.lat),
      u: e.u,
      v: e.v,
      velocidade: e.velocidade_ms,
    }));

    // O raio vem em graus e vira unidades do desenho pela própria projeção:
    // assim ele vale igual num mapa do Brasil inteiro e num de um estado só.
    const raio = Math.abs(projecao.px(RAIO_GRAUS) - projecao.px(0)) || 1;
    const raio2 = raio * raio;
    const baldes = agrupar(pontos, raio);

    const passoX = projecao.largura / colunas;
    const passoY = projecao.altura / linhas;

    for (let linha = 0; linha < linhas; linha++) {
      for (let coluna = 0; coluna < colunas; coluna++) {
        const x = (coluna + 0.5) * passoX;
        const y = (linha + 0.5) * passoY;

        const baldeX = Math.floor(x / raio);
        const baldeY = Math.floor(y / raio);

        let somaU = 0, somaV = 0, somaForca = 0, pesos = 0;
        for (let bx = baldeX - 1; bx <= baldeX + 1; bx++) {
          for (let by = baldeY - 1; by <= baldeY + 1; by++) {
            const vizinhos = baldes.get(`${bx},${by}`);
            if (!vizinhos) continue;

            for (const ponto of vizinhos) {
              const dx = ponto.x - x, dy = ponto.y - y;
              const distancia2 = dx * dx + dy * dy;
              if (distancia2 > raio2) continue;
              // Distância zero (a célula caiu em cima da estação) dividiria
              // por zero; o piso preserva o valor da própria estação.
              const peso = 1 / Math.pow(Math.max(distancia2, 1), POTENCIA_IDW / 2);
              somaU += ponto.u * peso;
              somaV += ponto.v * peso;
              somaForca += ponto.velocidade * peso;
              pesos += peso;
            }
          }
        }

        if (!pesos) continue;   // longe de tudo: sem vento desenhado
        const indice = linha * colunas + coluna;
        u[indice] = somaU / pesos;
        v[indice] = somaV / pesos;
        forca[indice] = somaForca / pesos;
        temDado[indice] = 1;
      }
    }

    return {
      colunas, linhas, passoX, passoY, u, v, forca, temDado,
      largura: projecao.largura,
      altura: projecao.altura,
      recorte: assarMascara(mascara, projecao, colunas, linhas),
    };
  }

  /* O vento numa posição do mapa, ou null onde não há o que desenhar: fora da
     área coberta pelas estações, ou fora da terra.

     A interpolação é BILINEAR entre as quatro células vizinhas, e não o valor
     da célula mais próxima. É o que separa um campo que parece um mapa de
     vento de um que parece um mosaico: pegando a célula mais próxima, a
     partícula anda em linha reta pelo interior da célula e vira de uma vez ao
     cruzar a borda — o rastro sai com cotovelos, todos alinhados numa grade
     invisível. Misturando as quatro, a direção muda continuamente e a
     trajetória curva, que é como o ar se comporta.

     Vizinho sem dado não entra como zero: o peso dele é descartado e o
     resultado é renormalizado pelos que sobraram. Contar o vazio como
     calmaria faria o vento morrer ao se aproximar da costa, e as partículas
     empacariam numa faixa ao longo de todo o litoral. */
  function amostrar(campo, x, y) {
    const recorte = campo.recorte;
    if (recorte) {
      const mx = Math.floor(x * recorte.escalaX);
      const my = Math.floor(y * recorte.escalaY);
      if (mx < 0 || my < 0 || mx >= recorte.largura || my >= recorte.altura) {
        return null;
      }
      if (!recorte.terra[my * recorte.largura + mx]) return null;
    }

    // O valor de uma célula vale no CENTRO dela, e não no canto: daí o meio
    // passo descontado. Sem ele o campo inteiro sai deslocado de meia célula.
    const fx = x / campo.passoX - 0.5;
    const fy = y / campo.passoY - 0.5;

    const coluna = Math.floor(fx);
    const linha = Math.floor(fy);
    const tx = fx - coluna;
    const ty = fy - linha;

    let u = 0, v = 0, forca = 0, pesos = 0;

    for (let dl = 0; dl <= 1; dl++) {
      for (let dc = 0; dc <= 1; dc++) {
        const c = coluna + dc;
        const l = linha + dl;
        if (c < 0 || l < 0 || c >= campo.colunas || l >= campo.linhas) continue;

        const indice = l * campo.colunas + c;
        if (!campo.temDado[indice]) continue;

        const peso = (dc ? tx : 1 - tx) * (dl ? ty : 1 - ty);
        u += campo.u[indice] * peso;
        v += campo.v[indice] * peso;
        forca += campo.forca[indice] * peso;
        pesos += peso;
      }
    }

    // Quase nenhum vizinho com dado: é borda do campo, não calmaria. Dividir
    // por um peso ínfimo daria um vetor enorme e arremessaria a partícula.
    if (pesos < 0.15) return null;

    return { u: u / pesos, v: v / pesos, forca: forca / pesos };
  }

  /* A cor de uma velocidade, na escala que a API mandou. */
  function corDaEscala(velocidade, escala) {
    for (const faixa of escala) {
      if (faixa.ate === null || velocidade < faixa.ate) return faixa.cor;
    }
    return escala[escala.length - 1].cor;
  }

  function camada(tela) {
    // O contexto é pedido uma vez, e não a cada quadro.
    const contexto = tela.getContext("2d");

    let campo = null;
    let escala = null;
    let particulas = [];
    let pedido = null;
    let ativo = false;
    let ultimo = 0;
    let ondeEstamos = null;    // devolve o enquadramento atual, vindo do app.js
    let vistaAnterior = "";

    /* Onde o desenho está agora: escala e deslocamento que levam um ponto do
       MAPA a um pixel de tela. */
    function vista() {
      const atual = ondeEstamos && ondeEstamos();
      if (atual) return atual;

      // Sem câmera (os mapas do painel): o SVG se ajusta à caixa com
      // `preserveAspectRatio` no padrão, que centraliza e deixa tarja. A conta
      // abaixo é essa mesma regra, para o vento pousar exatamente em cima do
      // desenho, e não deslocado dele.
      const largura = tela.clientWidth || 1;
      const altura = tela.clientHeight || 1;
      const comum = Math.min(largura / campo.largura, altura / campo.altura);
      return {
        escala: comum,
        deslocaX: (largura - campo.largura * comum) / 2,
        deslocaY: (altura - campo.altura * comum) / 2,
        largura,
        altura,
      };
    }

    /* O retângulo do MAPA que está de fato na tela.

       É o que mantém a densidade constante: as partículas nascem e vivem só
       aqui dentro. Espalhadas pelo mapa inteiro, ao aproximar um estado
       sobrariam as poucas que calhassem de estar nele — e o mapa ampliado
       parecia vazio. */
    function regiao(onde) {
      return {
        x0: Math.max(0, -onde.deslocaX / onde.escala),
        y0: Math.max(0, -onde.deslocaY / onde.escala),
        x1: Math.min(campo.largura, (onde.largura - onde.deslocaX) / onde.escala),
        y1: Math.min(campo.altura, (onde.altura - onde.deslocaY) / onde.escala),
      };
    }

    /* Ajusta o buffer à caixa na tela, na densidade real do monitor.

       Sem isto o canvas nasce com 300x150, o padrão do HTML, e é esticado por
       CSS — o mesmo borrão que tirar o canvas da câmera veio resolver. */
    function dimensionar() {
      const densidade = Math.min(devicePixelRatio || 1, 2);
      const largura = Math.round((tela.clientWidth || 1) * densidade);
      const altura = Math.round((tela.clientHeight || 1) * densidade);

      if (tela.width === largura && tela.height === altura) return false;

      tela.width = largura;
      tela.height = altura;
      // Daqui para a frente tudo é dito em pixels de CSS, e o navegador cuida
      // da densidade: um traço de 1,15 sai com 1,15 pixel de CSS na tela comum
      // e com 2,3 pixels reais numa retina — nítido, e não grosso.
      contexto.setTransform(densidade, 0, 0, densidade, 0, 0);
      return true;
    }

    /* Põe a partícula num ponto com vento. Sem a checagem, metade delas
       nasceria no oceano ou fora da área coberta e ficaria parada. */
    function nascer(particula, area) {
      const largura = Math.max(area.x1 - area.x0, 1);
      const altura = Math.max(area.y1 - area.y0, 1);

      for (let tentativa = 0; tentativa < 12; tentativa++) {
        const x = area.x0 + Math.random() * largura;
        const y = area.y0 + Math.random() * altura;
        if (amostrar(campo, x, y)) {
          particula.x = x;
          particula.y = y;
          particula.idade = Math.random() * VIDA;
          return;
        }
      }
      // Desistiu: fica fora e tenta de novo no quadro seguinte, sem rastro.
      // Insistir mais travaria o quadro quando a área coberta fosse pequena.
      particula.x = -1;
      particula.y = -1;
      particula.idade = VIDA;
    }

    function semear(quantidade, area) {
      particulas = Array.from({ length: quantidade }, () => ({
        x: -1, y: -1, idade: VIDA,
      }));
      for (const particula of particulas) nascer(particula, area);
    }

    function quadro(agora) {
      pedido = requestAnimationFrame(quadro);
      if (!campo || !ativo || document.hidden) return;

      // 30 quadros por segundo bastam para um campo de vento, e são metade do
      // trabalho de 60. O relógio é o do próprio navegador, então a animação
      // corre igual em tela de 60 Hz e de 144 Hz.
      if (agora - ultimo < INTERVALO) return;
      ultimo = agora;

      desenharQuadro();
    }

    function desenharQuadro() {
      const redimensionou = dimensionar();
      const onde = vista();
      const area = regiao(onde);

      // Quando a câmera se mexe, o rastro que está na tela descreve um
      // enquadramento que não existe mais, e apareceria escorregando por cima
      // do novo. Apagar de uma vez é o que o Windy faz ao arrastar o mapa.
      const assinatura = `${onde.escala.toFixed(4)}|${onde.deslocaX.toFixed(1)}`
                       + `|${onde.deslocaY.toFixed(1)}`;
      if (redimensionou || assinatura !== vistaAnterior) {
        vistaAnterior = assinatura;
        contexto.clearRect(0, 0, onde.largura, onde.altura);
        for (const particula of particulas) nascer(particula, area);
      }

      // Apaga o rastro antigo SEM pintar por cima: `destination-out` come a
      // opacidade do que já está desenhado. Um retângulo translúcido escuro,
      // que é o truque usual, escureceria o mapa por baixo — aqui a camada
      // precisa continuar transparente.
      contexto.globalCompositeOperation = "destination-out";
      contexto.globalAlpha = 1;
      contexto.fillStyle = "#000";
      contexto.fillRect(0, 0, onde.largura, onde.altura);
      contexto.globalCompositeOperation = "source-over";

      // Espessura em pixel de tela, sem divisão nenhuma: o canvas não é mais
      // ampliado por ninguém. O passo é que se divide pela escala, para o
      // rastro andar sempre à mesma velocidade na tela — perto ou longe.
      contexto.lineWidth = ESPESSURA;
      contexto.lineCap = "round";
      const passo = VELOCIDADE_VISUAL / onde.escala;

      // As partículas são agrupadas por cor: cada `stroke` custa uma chamada
      // ao rasterizador, e trocar de cor obriga a fechar o traçado. Assim são
      // ~7 traçados por quadro (um por faixa da escala) em vez de 2.600.
      const porCor = new Map();

      for (const particula of particulas) {
        const vento = amostrar(campo, particula.x, particula.y);
        // Fora de vista a partícula não é apagada, é recolhida: deixá-la
        // correndo pelo canteiro invisível gastaria o mesmo e não desenharia
        // nada.
        const foraDeVista = particula.x < area.x0 || particula.x > area.x1
                         || particula.y < area.y0 || particula.y > area.y1;

        if (!vento || foraDeVista || particula.idade >= VIDA) {
          nascer(particula, area);
          continue;
        }

        const x0 = particula.x;
        const y0 = particula.y;
        // O eixo y cresce para baixo, e `v` aponta para o norte: por isso ele
        // entra subtraindo. Trocar o sinal aqui inverteria o mapa inteiro no
        // sentido mais difícil de notar.
        particula.x += vento.u * passo;
        particula.y -= vento.v * passo;
        particula.idade += 1;

        const cor = corDaEscala(vento.forca, escala);
        let risco = porCor.get(cor);
        if (!risco) { risco = []; porCor.set(cor, risco); }

        risco.push(
          onde.deslocaX + x0 * onde.escala,
          onde.deslocaY + y0 * onde.escala,
          onde.deslocaX + particula.x * onde.escala,
          onde.deslocaY + particula.y * onde.escala,
        );
      }

      contexto.globalAlpha = OPACIDADE;
      for (const [cor, riscos] of porCor) {
        contexto.strokeStyle = cor;
        contexto.beginPath();
        for (let i = 0; i < riscos.length; i += 4) {
          contexto.moveTo(riscos[i], riscos[i + 1]);
          contexto.lineTo(riscos[i + 2], riscos[i + 3]);
        }
        contexto.stroke();
      }
      contexto.globalAlpha = 1;
    }

    /* Sem animação, o campo vira setas: uma por célula da grade, apontando
       para onde o vento vai. Diz a mesma coisa que o rastro, de uma vez. */
    function desenharSetas() {
      dimensionar();
      const onde = vista();
      contexto.clearRect(0, 0, onde.largura, onde.altura);

      const salto = Math.max(1, Math.round(campo.colunas / 26));

      contexto.lineWidth = 1.4;
      contexto.lineCap = "round";

      for (let linha = 0; linha < campo.linhas; linha += salto) {
        for (let coluna = 0; coluna < campo.colunas; coluna += salto) {
          const mx = (coluna + 0.5) * campo.passoX;
          const my = (linha + 0.5) * campo.passoY;

          const vento = amostrar(campo, mx, my);
          if (!vento) continue;

          const x = onde.deslocaX + mx * onde.escala;
          const y = onde.deslocaY + my * onde.escala;
          if (x < 0 || y < 0 || x > onde.largura || y > onde.altura) continue;

          const modulo = Math.hypot(vento.u, vento.v) || 1;
          const comprimento = 7 + Math.min(vento.forca, 9) * 2.2;
          const dx = (vento.u / modulo) * comprimento;
          const dy = -(vento.v / modulo) * comprimento;
          const angulo = Math.atan2(dy, dx);

          contexto.strokeStyle = corDaEscala(vento.forca, escala);
          contexto.beginPath();
          contexto.moveTo(x - dx / 2, y - dy / 2);
          contexto.lineTo(x + dx / 2, y + dy / 2);
          // Ponta: dois riscos curtos abrindo para trás, que é o que diz de
          // que lado da linha está a frente.
          for (const giro of [-0.45, 0.45]) {
            contexto.moveTo(x + dx / 2, y + dy / 2);
            contexto.lineTo(
              x + dx / 2 - Math.cos(angulo + giro) * 4.5,
              y + dy / 2 - Math.sin(angulo + giro) * 4.5,
            );
          }
          contexto.stroke();
        }
      }
    }

    return {
      /* Monta o campo e começa a desenhar. */
      desenhar(projecao, dados, mascara, enquadramento) {
        this.parar();
        campo = montarCampo(projecao, dados.estacoes, mascara);
        escala = dados.escala;
        ondeEstamos = enquadramento || null;
        vistaAnterior = "";

        dimensionar();
        const onde = vista();
        contexto.clearRect(0, 0, onde.largura, onde.altura);

        if (PARADO) { desenharSetas(); return; }

        // A quantidade acompanha a TELA, e não o mapa: é da área visível que
        // depende quantas partículas o olho encontra.
        const pixels = onde.largura * onde.altura;
        semear(
          Math.min(MAX_PARTICULAS,
                   Math.round(pixels / 1e6 * PARTICULAS_POR_MILHAO)),
          regiao(onde),
        );

        ativo = true;
        ultimo = 0;
        pedido = requestAnimationFrame(quadro);
      },

      /* Suspende o desenho sem perder o campo: é o que a troca de aba e a
         saída dos mapas usam. Um campo animando atrás de uma tela que ninguém
         está vendo gasta bateria e nada mais.

         O laço é cancelado de verdade, e não só marcado como inativo: um
         `requestAnimationFrame` que só serve para desistir ainda acorda a
         página 30 vezes por segundo. O campo fica guardado, então voltar é
         imediato — sem refazer a interpolação nem buscar de novo na API. */
      pausar() {
        ativo = false;
        if (pedido) cancelAnimationFrame(pedido);
        pedido = null;
      },

      seguir() {
        if (!campo || PARADO || ativo) return;
        ativo = true;
        ultimo = 0;
        if (!pedido) pedido = requestAnimationFrame(quadro);
      },

      parar() {
        ativo = false;
        if (pedido) cancelAnimationFrame(pedido);
        pedido = null;
      },

      limpar() {
        this.parar();
        campo = null;
        particulas = [];
        contexto.setTransform(1, 0, 0, 1, 0, 0);
        contexto.clearRect(0, 0, tela.width, tela.height);
      },
    };
  }

  return { camada };
})();
