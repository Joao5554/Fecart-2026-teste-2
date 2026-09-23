/* Relevo em três dimensões do Fecart 2026.

   Inclina o mapa e levanta o terreno: a mesma grade de altitudes que a camada
   2D usa para sombrear, aqui vira uma superfície que se pode girar com o
   mouse. Sem biblioteca nenhuma — nem three.js, nem WebGL —, pelo mesmo
   motivo do resto do projeto: tudo tem de rodar offline, de um `git clone`,
   sem CDN. O globo da tela de abertura (`cenario.js`) já faz projeção 3D em
   canvas 2D; este arquivo faz o mesmo com um mapa de altitudes.

   O que se vê
   -----------
   A superfície leva a cor do mapa plano: a escala hipsométrica com a mancha
   de risco por cima, translúcida. Não é enfeite — é a mesma leitura do mapa
   2D, vista de lado. Quem gira a cena continua olhando o risco, agora sabendo
   se aquele município está na serra ou na várzea.

   Como o desenho funciona
   -----------------------
   Três passos, e nenhum deles é misterioso:

   1. Cada ponto da grade vira um ponto no espaço: longitude para leste,
      latitude para norte, altitude para cima.
   2. O espaço é girado duas vezes — uma em torno do eixo vertical (o "giro",
      que o mouse controla na horizontal) e outra para inclinar a câmera (a
      "inclinação", que o mouse controla na vertical). Depois disso, cada
      ponto tem uma posição na tela e uma PROFUNDIDADE.
   3. Os quadriláteros entre pontos vizinhos são pintados do mais distante
      para o mais próximo. É o "algoritmo do pintor": quem está atrás é
      coberto por quem está na frente, e o resultado é oclusão correta sem
      nenhum buffer de profundidade por pixel.

   A cena tem tamanho 1
   --------------------
   Todas as coordenadas são reduzidas para uma cena de lado 1 antes de
   qualquer conta de câmera. Isso não é elegância: a distância da câmera vale
   2,6, e sem a redução ela ficaria comparável a uma janela de QUARENTA GRAUS
   de largura. O divisor da perspectiva passaria por zero no meio do mapa, e
   metade dos pontos sairia projetada do lado errado da tela — um leque de
   triângulos em vez de um país. Foi assim que esta cena apareceu na primeira
   vez que rodou.

   Por que não ordenar os quadriláteros com sort()
   -----------------------------------------------
   São dezenas de milhares por quadro, e um `sort` com comparador custa caro o
   bastante para derrubar a taxa de quadros durante o arrasto. No lugar dele,
   uma ordenação por contagem: a profundidade é discretizada em 1024 gavetas,
   e percorrer as gavetas de trás para frente já devolve a ordem. Custa uma
   passada em vez de n·log(n), e a precisão perdida é invisível — dois
   quadriláteros na mesma gaveta estão a menos de um pixel um do outro.

   O exagero vertical
   ------------------
   É inevitável e é declarado. O Brasil tem 4.300 km de largura e 2.995 m de
   altura máxima: na escala real, o relevo do país inteiro seria uma folha de
   papel — 0,07% da largura. A cena calcula o exagero para o ponto mais alto
   da janela ocupar cerca de 17% da largura dela, o que mantém a montanha
   visível tanto no país inteiro quanto num estado só. O número usado aparece
   no rodapé, porque quem olha um relevo 3D precisa saber que a serra não é
   aquilo tudo.
*/

window.Relevo3D = (() => {
  "use strict";

  const GRAUS = Math.PI / 180;
  const METROS_POR_GRAU = 111320;

  // Quantos pixels de tela cada célula da malha deve ocupar. Menor que isso e
  // o custo sobe sem nada aparecer; maior e a serra vira escada.
  const PIXELS_POR_CELULA = 5;
  const PIXELS_POR_CELULA_ARRASTANDO = 9;

  const MAX_CELULAS = 52000;
  const GAVETAS = 1024;

  /* Fora do país a textura é transparente, e o quadrilátero simplesmente não é
     desenhado. É o que dá ao terreno o formato do Brasil, em vez de uma placa
     retangular com o país pintado no meio dela. */
  const SEM_COR = 0x7fffffff;

  const INCLINACAO_MIN = 12;    // quase de lado
  const INCLINACAO_MAX = 89;    // quase de cima (o mapa plano)
  const DISTANCIA_MIN = 1.3;
  const DISTANCIA_MAX = 6.0;

  const ALVO_DE_RELEVO = 0.17;  // o pico ocupa 17% da largura da janela
  const EXAGERO_MIN = 15;
  const EXAGERO_MAX = 320;

  const NIVEIS_LUZ = 24;
  const NIVEIS_ALTURA = 40;

  /* As cores são pintadas como texto ("rgb(1,2,3)"), e montar esse texto por
     quadrilátero custaria mais que o desenho: são dezenas de milhares por
     quadro. A paleta é montada uma vez, com a cor já quantizada, e o desenho
     só troca um índice. */
  function paleta(corDaAltitude) {
    const cores = new Array(NIVEIS_ALTURA * NIVEIS_LUZ);
    for (let a = 0; a < NIVEIS_ALTURA; a++) {
      const [r, g, b] = corDaAltitude((a / (NIVEIS_ALTURA - 1)) * 2600);
      for (let l = 0; l < NIVEIS_LUZ; l++) {
        const brilho = 0.30 + 0.95 * (l / (NIVEIS_LUZ - 1));
        cores[a * NIVEIS_LUZ + l] =
          `rgb(${Math.min(255, r * brilho) | 0},`
          + `${Math.min(255, g * brilho) | 0},`
          + `${Math.min(255, b * brilho) | 0})`;
      }
    }
    return cores;
  }

  function cena(tela) {
    const contexto = tela.getContext("2d");

    let grade = null;          // { meta, alturas, sombra }
    let caixa = null;          // [lonOeste, latSul, lonLeste, latNorte]
    let textura = null;        // o mapa 2D já pintado, para vestir o terreno
    let fronteiras = null;     // GeoJSON das UFs, para desenhar por cima
    let cores = null;
    let exagero = 60;
    let maiorAltura = 1000;

    // Câmera. O giro começa em zero (norte para cima, como no mapa plano) e a
    // inclinação em 45°: a 55° a cena abria quase chapada, parecendo um mapa
    // plano torto em vez de um relevo, e a 30° o Brasil já fica deitado demais
    // para se reconhecer de relance.
    let giro = 0;
    let inclinacao = 45;
    let distancia = 2.6;

    let arrastando = false;
    let arrastandoAgora = false;
    let pedido = null;
    let ultimoX = 0;
    let ultimoY = 0;
    let aoMudar = null;

    // Saída do projetor. São variáveis, e não um array devolvido, porque o
    // projetor roda cinquenta mil vezes por quadro: devolver `[x, y, d]` seria
    // cinquenta mil objetos por quadro para o coletor de lixo recolher, e a
    // cena engasgaria justamente durante o arrasto.
    let saidaX = 0, saidaY = 0, saidaD = 0;

    // Buffers reaproveitados entre quadros, pelo mesmo motivo.
    let vx = null, vy = null, vd = null, vi = null;
    let quadGaveta = null, quadCor = null, quadOrdem = null;
    const contagem = new Int32Array(GAVETAS);
    const inicio = new Int32Array(GAVETAS);
    const cursor = new Int32Array(GAVETAS);
    let colunas = 0, linhas = 0;

    /** Altitude interpolada num ponto qualquer da grade. */
    function alturaNa(lon, lat) {
      const { meta, alturas } = grade;
      const coluna = (lon - meta.lon_oeste) / meta.passo_graus;
      const linha = (meta.lat_norte - lat) / meta.passo_graus;
      if (coluna < 0 || linha < 0
          || coluna > meta.largura - 1.001 || linha > meta.altura - 1.001) {
        return 0;
      }
      const c = Math.floor(coluna);
      const l = Math.floor(linha);
      const fx = coluna - c;
      const fy = linha - l;
      const a = l * meta.largura + c;
      const b = (l + 1) * meta.largura + c;
      return (alturas[a] * (1 - fx) + alturas[a + 1] * fx) * (1 - fy)
           + (alturas[b] * (1 - fx) + alturas[b + 1] * fx) * fy;
    }

    /** Sombreamento interpolado, de 0 (sombra) a 255 (encosta ao sol). */
    function luzNa(lon, lat) {
      const { meta, sombra } = grade;
      const coluna = (lon - meta.lon_oeste) / meta.passo_graus;
      const linha = (meta.lat_norte - lat) / meta.passo_graus;
      if (coluna < 0 || linha < 0
          || coluna > meta.largura - 1.001 || linha > meta.altura - 1.001) {
        return 200;
      }
      const c = Math.floor(coluna);
      const l = Math.floor(linha);
      const fx = coluna - c;
      const fy = linha - l;
      const a = l * meta.largura + c;
      const b = (l + 1) * meta.largura + c;
      return (sombra[a] * (1 - fx) + sombra[a + 1] * fx) * (1 - fy)
           + (sombra[b] * (1 - fx) + sombra[b + 1] * fx) * fy;
    }

    /** Escolhe quantas células a malha terá, pelo tamanho da tela. */
    function dimensionar(emArrasto) {
      const alvo = emArrasto
        ? PIXELS_POR_CELULA_ARRASTANDO : PIXELS_POR_CELULA;

      const larguraGeo = (caixa[2] - caixa[0])
                       * Math.cos(((caixa[1] + caixa[3]) / 2) * GRAUS);
      const alturaGeo = caixa[3] - caixa[1];
      const proporcao = alturaGeo / Math.max(larguraGeo, 1e-9);

      let cols = Math.round(tela.width / alvo);
      let lins = Math.round(cols * proporcao);

      if (cols * lins > MAX_CELULAS) {
        const fator = Math.sqrt(MAX_CELULAS / (cols * lins));
        cols = Math.round(cols * fator);
        lins = Math.round(lins * fator);
      }

      cols = Math.max(24, Math.min(cols, 520));
      lins = Math.max(24, Math.min(lins, 520));

      if (cols === colunas && lins === linhas) return;

      colunas = cols;
      linhas = lins;

      const vertices = (colunas + 1) * (linhas + 1);
      vx = new Float32Array(vertices);
      vy = new Float32Array(vertices);
      vd = new Float32Array(vertices);
      vi = new Float32Array(vertices);

      const quads = colunas * linhas;
      quadGaveta = new Int32Array(quads);
      quadCor = new Int32Array(quads);
      quadOrdem = new Int32Array(quads);
    }

    /**
     * Calcula o exagero vertical da janela atual.
     *
     * Procura o ponto mais alto de uma amostra (varrer a grade inteira a cada
     * quadro seria desperdício) e escolhe o fator que o faz ocupar
     * `ALVO_DE_RELEVO` da largura da cena.
     */
    function calcularExagero() {
      let maior = 0;
      const passos = 60;
      for (let i = 0; i <= passos; i++) {
        const lat = caixa[1] + (caixa[3] - caixa[1]) * (i / passos);
        for (let j = 0; j <= passos; j++) {
          const lon = caixa[0] + (caixa[2] - caixa[0]) * (j / passos);
          const h = alturaNa(lon, lat);
          if (h > maior) maior = h;
        }
      }
      maiorAltura = Math.max(maior, 50);

      const larguraGeo = (caixa[2] - caixa[0])
                       * Math.cos(((caixa[1] + caixa[3]) / 2) * GRAUS);
      const larguraMetros = larguraGeo * METROS_POR_GRAU;

      exagero = Math.max(EXAGERO_MIN, Math.min(EXAGERO_MAX,
        (ALVO_DE_RELEVO * larguraMetros) / maiorAltura));
    }

    /**
     * Monta a função que leva um ponto do mundo à tela.
     *
     * Existe uma só, e as duas coisas que desenham — a superfície e as
     * fronteiras — usam ela. Enquanto este arquivo teve duas cópias da mesma
     * conta, bastava uma delas mudar para a divisa do estado sair flutuando ao
     * lado da serra a que pertence.
     *
     * O resultado sai em `saidaX`, `saidaY` e `saidaD` em vez de ser
     * devolvido: ver o comentário na declaração dessas variáveis.
     */
    function criarProjetor() {
      const lonC = (caixa[0] + caixa[2]) / 2;
      const latC = (caixa[1] + caixa[3]) / 2;
      const cosLat = Math.cos(latC * GRAUS);

      const larguraGeo = (caixa[2] - caixa[0]) * cosLat;
      const alturaGeo = caixa[3] - caixa[1];

      // A redução para uma cena de lado 1. Ver o cabeçalho do arquivo: sem
      // ela, o divisor da perspectiva cruza o zero e a cena vira um leque.
      const norma = 1 / Math.max(larguraGeo, alturaGeo, 1e-9);

      const g = giro * GRAUS;
      const p = inclinacao * GRAUS;
      const cosG = Math.cos(g), senG = Math.sin(g);
      const cosP = Math.cos(p), senP = Math.sin(p);

      // A distância focal. Com a cena de lado 1 e a câmera a 2,6, é o que faz
      // o país ocupar a tela; mexer na distância é que dá o zoom.
      const foco = Math.min(tela.width, tela.height) * 2.2;
      const centroX = tela.width / 2;
      const centroY = tela.height / 2 + tela.height * 0.06;

      const alturaParaCena = (exagero / METROS_POR_GRAU) * norma;

      return function projetarPonto(lon, lat, altura) {
        const x = (lon - lonC) * cosLat * norma;
        const y = (lat - latC) * norma;
        const z = altura * alturaParaCena;

        // Giro em torno do eixo vertical.
        const x1 = x * cosG + y * senG;
        const y1 = -x * senG + y * cosG;

        // Inclinação: 90° é olhar de cima (o mapa plano), 0° é do nível do
        // chão. `u` é o quanto o ponto sobe na tela; `d`, o quanto ele está
        // longe da câmera.
        const u = y1 * senP + z * cosP;
        const d = y1 * cosP - z * senP;

        // O piso no divisor é cinto de segurança: com a cena normalizada ele
        // nunca deveria ser atingido, e se for, um ponto sai no lugar errado
        // em vez de a cena inteira explodir.
        const divisor = Math.max(distancia + d, 0.15);

        saidaX = centroX + (x1 * foco) / divisor;
        saidaY = centroY - (u * foco) / divisor;
        saidaD = d;
      };
    }

    function projetar(projetarPonto) {
      let k = 0;
      for (let l = 0; l <= linhas; l++) {
        const lat = caixa[3] - (caixa[3] - caixa[1]) * (l / linhas);
        for (let c = 0; c <= colunas; c++, k++) {
          const lon = caixa[0] + (caixa[2] - caixa[0]) * (c / colunas);
          vi[k] = luzNa(lon, lat);
          projetarPonto(lon, lat, alturaNa(lon, lat));
          vx[k] = saidaX;
          vy[k] = saidaY;
          vd[k] = saidaD;
        }
      }
    }

    /**
     * De que cor é uma célula.
     *
     * Número positivo: índice na paleta hipsométrica. Negativo: a cor vem da
     * textura, e o número guarda onde. `SEM_COR`: fora do país, não desenha.
     */
    function corDaCelula(lon, lat, luz) {
      const nivelLuz = Math.max(0, Math.min(NIVEIS_LUZ - 1,
        Math.round((luz / 255) * (NIVEIS_LUZ - 1))));

      if (textura) {
        const tx = Math.round((lon - caixa[0]) / (caixa[2] - caixa[0])
                              * (textura.largura - 1));
        const ty = Math.round((caixa[3] - lat) / (caixa[3] - caixa[1])
                              * (textura.altura - 1));
        if (tx < 0 || ty < 0 || tx >= textura.largura || ty >= textura.altura) {
          return SEM_COR;
        }
        const pos = (ty * textura.largura + tx) * 4;
        if (textura.dados[pos + 3] <= 8) return SEM_COR;
        return -((pos >> 2) * NIVEIS_LUZ + nivelLuz) - 1;
      }

      const nivelAltura = Math.max(0, Math.min(NIVEIS_ALTURA - 1,
        Math.round((alturaNa(lon, lat) / 2600) * (NIVEIS_ALTURA - 1))));
      return nivelAltura * NIVEIS_LUZ + nivelLuz;
    }

    /* Índice negativo quer dizer "cor vinda da textura": o número guarda a
       posição do pixel e o nível de luz, e a cor sai da multiplicação dos dois
       na hora. Positivo é a escala hipsométrica, que já está na paleta. */
    function estiloDaCor(indice) {
      if (indice >= 0) return cores[indice] || "#334";

      const bruto = -indice - 1;
      const nivelLuz = bruto % NIVEIS_LUZ;
      const pos = ((bruto - nivelLuz) / NIVEIS_LUZ) * 4;
      const brilho = 0.30 + 0.95 * (nivelLuz / (NIVEIS_LUZ - 1));
      const dados = textura.dados;

      return `rgb(${Math.min(255, dados[pos] * brilho) | 0},`
           + `${Math.min(255, dados[pos + 1] * brilho) | 0},`
           + `${Math.min(255, dados[pos + 2] * brilho) | 0})`;
    }

    function desenhar() {
      if (!grade || !caixa || !tela.width) return;

      dimensionar(arrastandoAgora);
      calcularExagero();
      const projetarPonto = criarProjetor();
      projetar(projetarPonto);

      contexto.setTransform(1, 0, 0, 1, 0, 0);
      contexto.clearRect(0, 0, tela.width, tela.height);

      let menor = Infinity, maior = -Infinity;
      for (let k = 0; k < vd.length; k++) {
        if (vd[k] < menor) menor = vd[k];
        if (vd[k] > maior) maior = vd[k];
      }
      const faixa = Math.max(maior - menor, 1e-6);

      contagem.fill(0);

      const total = colunas * linhas;
      for (let l = 0, q = 0; l < linhas; l++) {
        const lat = caixa[3] - (caixa[3] - caixa[1]) * ((l + 0.5) / linhas);
        const acima = l * (colunas + 1);
        const abaixo = (l + 1) * (colunas + 1);

        for (let c = 0; c < colunas; c++, q++) {
          const a = acima + c;
          const b = abaixo + c;
          const profundidade = (vd[a] + vd[a + 1] + vd[b] + vd[b + 1]) / 4;

          const gaveta = Math.max(0, Math.min(GAVETAS - 1,
            (((profundidade - menor) / faixa) * (GAVETAS - 1)) | 0));
          quadGaveta[q] = gaveta;
          contagem[gaveta]++;

          const lon = caixa[0] + (caixa[2] - caixa[0]) * ((c + 0.5) / colunas);
          const luz = (vi[a] + vi[a + 1] + vi[b] + vi[b + 1]) / 4;
          quadCor[q] = corDaCelula(lon, lat, luz);
        }
      }

      // Ordenação por contagem: as gavetas viram deslocamentos, e uma segunda
      // passada põe cada quadrilátero no seu lugar. Da mais funda para a mais
      // próxima, que é a ordem em que o pintor trabalha.
      let acumulado = 0;
      for (let g = GAVETAS - 1; g >= 0; g--) {
        inicio[g] = acumulado;
        acumulado += contagem[g];
      }
      cursor.set(inicio);
      for (let q = 0; q < total; q++) {
        quadOrdem[cursor[quadGaveta[q]]++] = q;
      }

      // Quadriláteros vizinhos quase sempre caem na mesma cor quantizada,
      // então eles entram num caminho só e saem num `fill` só — trocar
      // `fillStyle` é o que custa caro aqui, não a geometria.
      let corAtual = SEM_COR;
      let aberto = false;

      for (let i = 0; i < total; i++) {
        const q = quadOrdem[i];
        const cor = quadCor[q];
        if (cor === SEM_COR) continue;

        if (cor !== corAtual) {
          if (aberto) contexto.fill();
          contexto.fillStyle = estiloDaCor(cor);
          contexto.beginPath();
          corAtual = cor;
          aberto = true;
        }

        const l = (q / colunas) | 0;
        const c = q - l * colunas;
        const a = l * (colunas + 1) + c;
        const b = (l + 1) * (colunas + 1) + c;

        contexto.moveTo(vx[a], vy[a]);
        contexto.lineTo(vx[a + 1], vy[a + 1]);
        contexto.lineTo(vx[b + 1], vy[b + 1]);
        contexto.lineTo(vx[b], vy[b]);
        contexto.closePath();
      }
      if (aberto) contexto.fill();

      if (fronteiras) desenharFronteiras(projetarPonto);
    }

    /**
     * As divisas dos estados, deitadas sobre o terreno.
     *
     * Cada vértice da fronteira recebe a altitude do ponto em que cai, então a
     * linha sobe a serra junto com o chão em vez de flutuar sobre ele. Sem
     * isso, a divisa de Minas com o Rio passaria voando por cima da
     * Mantiqueira.
     */
    function desenharFronteiras(projetarPonto) {
      // Um empurrãozinho para cima, senão a linha briga com a superfície e
      // some em pedaços conforme a cena gira.
      const levantar = maiorAltura * 0.03;

      // Sem folga nenhuma: o terreno acaba exatamente na janela, e um vértice
      // de fronteira um grau além dela sai desenhado no vazio, como uma linha
      // branca flutuando ao lado do mapa. Era o que acontecia com margem.
      const dentro = (lon, lat) =>
        lon >= caixa[0] && lon <= caixa[2]
        && lat >= caixa[1] && lat <= caixa[3];

      const tracar = () => {
        for (const feicao of fronteiras.features || []) {
          const geo = feicao.geometry;
          if (!geo) continue;
          const poligonos = geo.type === "Polygon"
            ? [geo.coordinates] : geo.coordinates;

          for (const poligono of poligonos) {
            for (const anel of poligono) {
              let iniciado = false;
              // Um vértice a cada dois: a fronteira tem mais vértices do que a
              // tela tem pixels aqui, e cada um custa uma busca na grade.
              for (let i = 0; i < anel.length; i += 2) {
                const lon = anel[i][0];
                const lat = anel[i][1];
                if (!dentro(lon, lat)) { iniciado = false; continue; }

                projetarPonto(lon, lat, alturaNa(lon, lat) + levantar);
                if (iniciado) contexto.lineTo(saidaX, saidaY);
                else { contexto.moveTo(saidaX, saidaY); iniciado = true; }
              }
            }
          }
        }
      };

      contexto.lineJoin = "round";
      contexto.lineCap = "round";

      // Dobrada, como no mapa plano: escura por baixo, clara por cima, para
      // aparecer tanto sobre o verde da planície quanto sobre o claro do pico.
      contexto.beginPath();
      tracar();
      contexto.strokeStyle = "rgba(4, 8, 16, .8)";
      contexto.lineWidth = 3.2;
      contexto.stroke();

      contexto.beginPath();
      tracar();
      contexto.strokeStyle = "rgba(234, 243, 255, .95)";
      contexto.lineWidth = 1.2;
      contexto.stroke();
    }

    function agendar() {
      if (pedido) return;
      pedido = requestAnimationFrame(() => {
        pedido = null;
        desenhar();
      });
    }

    // ---------------------------------------------------------------------
    // Controles
    // ---------------------------------------------------------------------

    function girarPara(novoGiro, novaInclinacao) {
      giro = ((novoGiro % 360) + 360) % 360;
      inclinacao = Math.max(INCLINACAO_MIN,
                            Math.min(INCLINACAO_MAX, novaInclinacao));
      agendar();
      if (aoMudar) aoMudar();
    }

    function aoApertar(evento) {
      arrastando = true;
      arrastandoAgora = true;
      ultimoX = evento.clientX;
      ultimoY = evento.clientY;
      if (tela.setPointerCapture) tela.setPointerCapture(evento.pointerId);
      tela.classList.add("arrastando");
    }

    function aoMover(evento) {
      if (!arrastando) return;
      const dx = evento.clientX - ultimoX;
      const dy = evento.clientY - ultimoY;
      ultimoX = evento.clientX;
      ultimoY = evento.clientY;
      girarPara(giro - dx * 0.4, inclinacao + dy * 0.3);
    }

    function aoSoltar(evento) {
      if (!arrastando) return;
      arrastando = false;
      if (tela.releasePointerCapture) {
        try { tela.releasePointerCapture(evento.pointerId); } catch (e) { /* já solto */ }
      }
      tela.classList.remove("arrastando");

      // A malha fina só volta quando o arrasto termina: girar com cinquenta
      // mil células engasgaria, e ninguém repara na malha grossa enquanto a
      // cena está em movimento.
      arrastandoAgora = false;
      agendar();
    }

    function aoRolar(evento) {
      evento.preventDefault();
      distancia = Math.max(DISTANCIA_MIN, Math.min(DISTANCIA_MAX,
        distancia * Math.exp(evento.deltaY * 0.0012)));
      agendar();
      if (aoMudar) aoMudar();
    }

    return {
      montar(dados) {
        grade = dados.grade;
        caixa = dados.caixa;
        textura = dados.textura || null;
        fronteiras = dados.fronteiras || null;
        cores = paleta(dados.corDaAltitude);
        aoMudar = dados.aoMudar || null;
        colunas = linhas = 0;      // força remontar a malha
      },

      redimensionar(largura, altura) {
        if (!largura || !altura) return;
        tela.width = largura;
        tela.height = altura;
        colunas = linhas = 0;
        agendar();
      },

      desenhar: agendar,

      /** Volta à posição inicial: norte para cima, inclinado a 45°. */
      reiniciar() {
        giro = 0;
        inclinacao = 45;
        distancia = 2.6;
        agendar();
        if (aoMudar) aoMudar();
      },

      estado: () => ({
        giro: Math.round(giro),
        inclinacao: Math.round(inclinacao),
        exagero: Math.round(exagero),
        celulas: colunas * linhas,
      }),

      ligarControles() {
        tela.addEventListener("pointerdown", aoApertar);
        tela.addEventListener("pointermove", aoMover);
        tela.addEventListener("pointerup", aoSoltar);
        tela.addEventListener("pointercancel", aoSoltar);
        tela.addEventListener("wheel", aoRolar, { passive: false });
      },

      desligarControles() {
        tela.removeEventListener("pointerdown", aoApertar);
        tela.removeEventListener("pointermove", aoMover);
        tela.removeEventListener("pointerup", aoSoltar);
        tela.removeEventListener("pointercancel", aoSoltar);
        tela.removeEventListener("wheel", aoRolar);
        arrastando = false;
        arrastandoAgora = false;
      },

      limpar() {
        this.desligarControles();
        if (pedido) cancelAnimationFrame(pedido);
        pedido = null;
        contexto.setTransform(1, 0, 0, 1, 0, 0);
        contexto.clearRect(0, 0, tela.width, tela.height);
        grade = null;
        textura = null;
        fronteiras = null;
      },
    };
  }

  return { cena };
})();
