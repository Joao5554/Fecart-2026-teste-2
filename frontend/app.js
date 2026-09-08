/* Interface do projeto Fecart 2026.
   JavaScript puro, sem bibliotecas: tudo roda localmente, junto com a API. */

// Servida pela própria API (http://127.0.0.1:8000/app), a origem é a mesma.
// Aberta com Live Server ou direto do arquivo, aponta para o uvicorn.
const API = (location.protocol === "file:" || location.port !== "8000")
  ? "http://127.0.0.1:8000"
  : location.origin;

const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

const CORES = { baixo: "#2E7D32", medio: "#F9A825", alto: "#C62828" };

// Tipos de desastre, iguais aos de src/esquema.py (GRUPOS_COBRADE).
// Ficam aqui para o formulário funcionar mesmo antes de a API responder.
// O teste testes/test_frontend.py falha se esta lista sair de sincronia
// com o esquema do projeto.
const TIPOS_DESASTRE = [
  "ESTIAGEM_SECA", "INUNDACAO", "ENXURRADA", "ALAGAMENTO", "CHUVAS_INTENSAS",
  "DESLIZAMENTO", "VENDAVAL_CICLONE", "GRANIZO", "INCENDIO_FLORESTAL", "EROSAO",
];

const EXPLICACAO = {
  baixo: "Nenhuma ocorrência esperada para este mês, segundo o histórico.",
  medio: "Ocorrência provável, sem sinal de gravidade excepcional.",
  alto: "Ocorrência provável com gravidade alta — o tipo de caso que costuma "
      + "gerar decreto de emergência ou vítimas.",
};

// Nomes amigáveis das variáveis históricas, para a caixa "como o modelo chegou a isso".
const ROTULOS = {
  ocorrencias_12m: "Ocorrências nos últimos 12 meses",
  ocorrencias_24m: "Ocorrências nos últimos 24 meses",
  ocorrencias_60m: "Ocorrências nos últimos 5 anos",
  ocorrencias_total_historico: "Total já registrado no município",
  meses_desde_ultima_ocorrencia: "Meses desde a última ocorrência",
  ja_ocorreu: "Já ocorreu alguma vez",
  anos_de_historico: "Anos de histórico",
  ocorrencias_mesmo_mes_historico: "Vezes que ocorreu neste mesmo mês",
  reconhecimentos_historico: "Emergências reconhecidas",
  mortos_historico: "Mortos em ocorrências anteriores",
  afetados_historico: "Afetados em ocorrências anteriores",
  prejuizo_historico_log: "Prejuízo acumulado (escala log)",
  ocorrencias_municipio_12m: "Ocorrências de qualquer tipo (12 meses)",
  ocorrencias_uf_grupo_12m: "Ocorrências deste tipo na UF (12 meses)",
  // Faixas disjuntas, usadas só na análise de odds ratio.
  ocorrencias_13_a_24m: "Ocorrências entre 13 e 24 meses atrás",
  ocorrencias_25_a_60m: "Ocorrências entre 25 e 60 meses atrás",
};

let municipioEscolhido = null;
let temporizadorBusca = null;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

async function iniciar() {
  // Meses e tipos são listas fixas: preenchidas ANTES de qualquer chamada de
  // rede. Se dependessem da API, uma falha de conexão deixaria o formulário
  // vazio e sem explicação — foi exatamente o que acontecia antes.
  preencherMeses();
  preencherTipos(TIPOS_DESASTRE);
  prepararMapa();
  prepararMapaDoAno();

  // Menu e tema são de interface pura: não dependem da API e precisam
  // funcionar mesmo com o servidor fora do ar, quando a página vira só um
  // aviso de erro que a pessoa ainda tem de conseguir ler no tema que escolheu.
  ligarTema();
  ligarMenu();
  ligarCamadasDeChuva();

  // O mapa por ano lê o Atlas direto, sem passar pelo modelo. Por isso é
  // carregado aqui, fora da verificação de modelo treinado logo abaixo: se o
  // modelo faltar, a previsão para, mas o histórico continua de pé.
  carregarAnos();

  try {
    const estado = await pedir("/");

    // O servidor é a fonte da verdade: se ele conhecer outros tipos (porque
    // alguém mudou src/esquema.py), a lista local é substituída.
    if (estado.tipos_de_desastre && estado.tipos_de_desastre.length) {
      preencherTipos(estado.tipos_de_desastre);
    }

    if (!estado.modelo_carregado) {
      bloquearFormulario(estado.mensagem || "O modelo ainda não foi treinado.");
      return;
    }

    const info = await pedir("/modelo/info");
    if (info.linhas_de_treino) {
      $("numero-modelo").textContent =
        (info.linhas_de_treino / 1000).toFixed(0) + " mil";
    }
    $("rodape-modelo").textContent =
      `Modelo treinado em ${formatarData(info.treinado_em)} · `
      + `origem dos dados: ${info.origem_dados} · `
      + `${(info.linhas_de_treino || 0).toLocaleString("pt-BR")} linhas`;
    if (info.aviso) mostrarAviso(info.aviso, false);

    mostrarOddsRatio();
  } catch (erro) {
    const abertoComoArquivo = location.protocol === "file:";
    bloquearFormulario(
      "Não foi possível falar com a API.\n\n"
      + (abertoComoArquivo
        ? "Esta página foi aberta direto do arquivo, e o navegador bloqueia "
          + "esse tipo de acesso.\n\n"
          + "Suba o servidor a partir da raiz do projeto:\n"
          + "    uvicorn backend.app:app --reload\n\n"
          + "e abra http://127.0.0.1:8000/app"
        : "Verifique se o servidor está no ar:\n"
          + "    uvicorn backend.app:app --reload")
    );
  }
}

function bloquearFormulario(mensagem) {
  mostrarAviso(mensagem, true);
  $("botao").disabled = true;
  $("busca").disabled = true;
  $("busca").placeholder = "indisponível — veja o aviso acima";
}

function preencherMeses() {
  const seletor = $("mes");
  const mesAtual = new Date().getMonth();
  MESES.forEach((nome, i) => {
    const opcao = new Option(nome, i + 1, false, i === mesAtual);
    seletor.add(opcao);
  });
}

function preencherTipos(tipos) {
  const seletor = $("tipo");
  const escolhaAtual = seletor.value;

  seletor.innerHTML = "";
  (tipos || []).forEach((tipo) => {
    seletor.add(new Option(formatarTipo(tipo), tipo));
  });

  // Não perde a escolha da pessoa quando a lista é atualizada pela API.
  if (escolhaAtual && tipos.includes(escolhaAtual)) seletor.value = escolhaAtual;
}

// ---------------------------------------------------------------------------
// Busca de município (autocomplete)
// ---------------------------------------------------------------------------

$("busca").addEventListener("input", (evento) => {
  const termo = evento.target.value.trim();
  municipioEscolhido = null;
  $("botao").disabled = true;
  $("municipio-escolhido").classList.add("oculto");

  clearTimeout(temporizadorBusca);
  if (termo.length < 3) {
    $("sugestoes").classList.add("oculto");
    return;
  }
  // Espera a pessoa parar de digitar antes de consultar a API.
  temporizadorBusca = setTimeout(() => buscarMunicipios(termo), 250);
});

async function buscarMunicipios(termo) {
  try {
    const dados = await pedir(`/municipios?busca=${encodeURIComponent(termo)}&limite=8`);
    const lista = $("sugestoes");
    lista.innerHTML = "";

    if (!dados.municipios.length) {
      lista.innerHTML = '<li class="uf">Nenhum município encontrado no Atlas</li>';
      lista.classList.remove("oculto");
      return;
    }

    dados.municipios.forEach((m) => {
      const item = document.createElement("li");
      item.innerHTML = `${m.municipio} <span class="uf">— ${m.uf} · `
                     + `${m.ocorrencias} ocorrência(s)</span>`;
      item.onclick = () => escolherMunicipio(m);
      lista.appendChild(item);
    });
    lista.classList.remove("oculto");
  } catch (erro) {
    /* silencioso: a busca é auxiliar e o erro já aparece no envio */
  }
}

function escolherMunicipio(m) {
  municipioEscolhido = m;
  $("busca").value = m.municipio;
  $("sugestoes").classList.add("oculto");
  $("municipio-escolhido").textContent =
    `${m.municipio} — ${m.uf} (${m.regiao}) · ${m.ocorrencias} ocorrências no Atlas`;
  $("municipio-escolhido").classList.remove("oculto");
  $("botao").disabled = false;
  carregarHistorico(m.codigo_ibge);
}

document.addEventListener("click", (evento) => {
  if (!evento.target.closest(".campo-busca")) {
    $("sugestoes").classList.add("oculto");
  }
});

// ---------------------------------------------------------------------------
// Previsão
// ---------------------------------------------------------------------------

$("formulario").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (!municipioEscolhido) return;

  const tipo = $("tipo").value;
  const mes = Number($("mes").value);
  const ano = new Date().getFullYear();

  $("botao").disabled = true;
  $("botao").textContent = "Calculando...";

  try {
    const previsao = await pedir("/prever/municipio", {
      codigo_ibge: municipioEscolhido.codigo_ibge,
      grupo_desastre: tipo, mes, ano,
    });
    mostrarResultado(previsao);
    await mostrarAno(municipioEscolhido.codigo_ibge, tipo, ano, mes);
    await mostrarMapaDaCidade(municipioEscolhido.codigo_ibge, tipo, mes);
  } catch (erro) {
    mostrarAviso(`Não foi possível prever: ${erro.message}`, true);
  } finally {
    $("botao").disabled = false;
    $("botao").textContent = "Prever risco";
  }
});

function mostrarResultado(p) {
  $("resultado").classList.remove("oculto");

  $("selo").textContent = p.nivel_risco;
  $("selo").className = `selo ${p.nivel_risco}`;

  $("resultado-titulo").textContent =
    `${p.municipio} (${p.uf}) — ${formatarTipo(p.grupo_desastre)} em ${MESES[p.mes - 1]}`;
  $("resultado-detalhe").textContent =
    `${EXPLICACAO[p.nivel_risco]} Confiança do modelo: ${porcento(p.confianca)}.`;

  const barras = $("barras");
  barras.innerHTML = "";
  ["baixo", "medio", "alto"].forEach((nivel) => {
    const valor = p.probabilidades[nivel] || 0;
    const linha = document.createElement("div");
    linha.className = "barra-linha";
    linha.innerHTML =
      `<span class="barra-nome">${nivel}</span>
       <div class="barra-trilho">
         <div class="barra-preenchida" style="width:${(valor * 100).toFixed(1)}%;
              background:${CORES[nivel]}"></div>
       </div>
       <span class="barra-valor">${porcento(valor)}</span>`;
    barras.appendChild(linha);
  });

  const tabela = $("tabela-features");
  tabela.innerHTML = "<tr><th>Variável</th><th>Valor</th></tr>";
  Object.entries(p.historico_usado).forEach(([chave, valor]) => {
    const linha = tabela.insertRow();
    linha.insertCell().textContent = ROTULOS[chave] || chave;
    const celula = linha.insertCell();
    celula.className = "numero";
    celula.textContent = formatarValor(chave, valor);
  });

  $("resultado").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function mostrarAno(codigoIbge, tipo, ano, mesEscolhido) {
  const pedidos = MESES.map((_, i) =>
    pedir("/prever/municipio", {
      codigo_ibge: codigoIbge, grupo_desastre: tipo, mes: i + 1, ano,
    }));
  const previsoes = await Promise.all(pedidos);

  const valores = previsoes.map((p) => p.probabilidades.alto || 0);
  const maximo = Math.max(...valores, 0.01);

  const grafico = $("grafico");
  grafico.innerHTML = "";
  valores.forEach((valor, i) => {
    const coluna = document.createElement("div");
    coluna.className = "coluna" + (i + 1 === mesEscolhido ? " destaque" : "");
    coluna.innerHTML =
      `<span class="coluna-valor">${porcento(valor)}</span>
       <div class="coluna-barra" style="height:${(valor / maximo) * 100}%"></div>
       <span class="coluna-mes">${MESES[i].slice(0, 3)}</span>`;
    coluna.title = `${MESES[i]}: ${porcento(valor)} de risco alto`;
    grafico.appendChild(coluna);
  });

  $("secao-ano").classList.remove("oculto");
}

// ---------------------------------------------------------------------------
// Mapa do Brasil
// ---------------------------------------------------------------------------

// A malha tem ~3 MB: é buscada uma vez e reaproveitada em todos os desenhos.
let malhaCache = null;

const UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
             "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"];

// Os dois primeiros dígitos do código IBGE identificam a UF. Guardar esse
// mapa evita uma consulta extra só para filtrar o mapa por estado.
const PREFIXO_UF = {
  11:"RO",12:"AC",13:"AM",14:"RR",15:"PA",16:"AP",17:"TO",21:"MA",22:"PI",
  23:"CE",24:"RN",25:"PB",26:"PE",27:"AL",28:"SE",29:"BA",31:"MG",32:"ES",
  33:"RJ",35:"SP",41:"PR",42:"SC",43:"RS",50:"MS",51:"MT",52:"GO",53:"DF",
};

const ufDoCodigo = (codigo) => PREFIXO_UF[Math.floor(codigo / 100000)];

function prepararMapa() {
  const tipo = $("mapa-tipo");
  TIPOS_DESASTRE.forEach((t) => tipo.add(new Option(formatarTipo(t), t)));
  tipo.value = "INUNDACAO";

  const mes = $("mapa-mes");
  MESES.forEach((nome, i) => mes.add(new Option(nome, i + 1, false, i === 1)));

  const uf = $("mapa-uf");
  uf.add(new Option("Brasil inteiro", ""));
  UFS.forEach((sigla) => uf.add(new Option(sigla, sigla)));

  $("form-mapa").addEventListener("submit", (evento) => {
    evento.preventDefault();
    desenharMapa(tipo.value, Number(mes.value), uf.value);
  });
}

async function desenharMapa(tipo, mes, ufEscolhida = "") {
  const botao = $("mapa-botao");
  botao.disabled = true;
  botao.textContent = "Desenhando...";
  $("mapa-estado").textContent = malhaCache
    ? "Calculando o risco de cada município..."
    : "Baixando as fronteiras dos municípios (3 MB, só na primeira vez)...";

  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    const dados = await pedir(
      `/mapa/brasil?grupo_desastre=${tipo}&mes=${mes}&ano=${new Date().getFullYear()}`
    );

    // Filtrar por UF muda o enquadramento: os limites do desenho passam a ser
    // os do estado, e ele preenche a tela em vez de virar um ponto no país.
    const soDoEstado = (codigo) => !ufEscolhida || ufDoCodigo(codigo) === ufEscolhida;

    const feicoes = malhaCache.features.filter(
      (f) => soDoEstado(f.properties.codigo_ibge)
    );
    const doMapa = dados.municipios.filter((m) => soDoEstado(m.codigo_ibge));
    const porMunicipio = new Map(doMapa.map((m) => [m.codigo_ibge, m]));

    renderizarSvg("mapa-svg", "mapa-dica", feicoes, porMunicipio);
    aplicarAnimacao("mapa-animacao", tipo);
    atualizarChuva("mapa");

    const resumo = { baixo: 0, medio: 0, alto: 0 };
    doMapa.forEach((m) => { resumo[m.nivel_risco] += 1; });

    const onde = ufEscolhida ? `em ${ufEscolhida}` : "no Brasil";
    $("mapa-estado").textContent =
      `${formatarTipo(tipo)} em ${MESES[mes - 1]}, ${onde} · `
      + `${doMapa.length.toLocaleString("pt-BR")} municípios com histórico · `
      + `${resumo.alto} em risco alto, ${resumo.medio} em médio.`;

    montarLegenda("mapa-legenda", resumo);
  } catch (erro) {
    $("mapa-estado").textContent = `Não foi possível montar o mapa: ${erro.message}`;
  } finally {
    botao.disabled = false;
    botao.textContent = "Desenhar";
  }
}

// ---------------------------------------------------------------------------
// Mapa da cidade e da região
// ---------------------------------------------------------------------------

async function mostrarMapaDaCidade(codigoIbge, tipo, mes) {
  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");
    const dados = await pedir(
      `/mapa/municipio/${codigoIbge}?grupo_desastre=${tipo}&mes=${mes}`
      + `&ano=${new Date().getFullYear()}`
    );

    const daRegiao = new Set(dados.codigos_da_vizinhanca);
    const feicoes = malhaCache.features.filter(
      (f) => daRegiao.has(f.properties.codigo_ibge)
    );
    if (!feicoes.length) return;

    const porMunicipio = new Map(dados.municipios.map((m) => [m.codigo_ibge, m]));
    renderizarSvg("cidade-svg", "cidade-dica", feicoes, porMunicipio, codigoIbge);
    aplicarAnimacao("cidade-animacao", tipo);
    atualizarChuva("cidade");

    const resumo = { baixo: 0, medio: 0, alto: 0 };
    dados.municipios.forEach((m) => { resumo[m.nivel_risco] += 1; });
    montarLegenda("cidade-legenda", resumo);

    $("cidade-setores").innerHTML = textoDosSetores(dados);
    $("secao-cidade").classList.remove("oculto");
  } catch (erro) {
    $("secao-cidade").classList.add("oculto");
  }
}

function textoDosSetores(dados) {
  const s = dados.setores_afetados || {};
  if (!s.disponivel) {
    return "O Atlas não registrou quais partes da cidade foram atingidas "
         + "nas ocorrências deste tipo.";
  }
  return `<strong>${s.setores_distintos} setores censitários</strong> desta `
       + `cidade já foram atingidos por ${formatarTipo(dados.grupo_desastre)}, `
       + `em ${s.ocorrencias_com_setor} das ${s.ocorrencias_do_tipo} ocorrências `
       + `registradas. O IBGE não publica o desenho desses setores, então o `
       + `número aparece sem o mapa de bairros.`;
}

// ---------------------------------------------------------------------------
// Camada de chuva medida
// ---------------------------------------------------------------------------
// Desenha, sobre o mapa, quanto choveu de fato — medido pelas estações
// automáticas do INMET.
//
// O ponto delicado é de onde vem o número. O arquivo que alimenta o modelo
// tem uma linha por município, mas em 92% delas a chuva foi medida em outro
// município: só 8% do país tem estação própria. Pintar município a município
// com esses valores desenharia uma precisão que não existe.
//
// Por isso a camada trabalha com os PONTOS: interpola entre as ~600 estações
// reais (é o que o Windy faz entre os pontos da grade dele) e desenha os
// marcadores por cima. Quem olha vê a mancha e vê de onde ela veio.

const GRADE_CHUVA = 72;   // resolução do cálculo, antes de o navegador suavizar
const RAIO_CHUVA = 3.2;   // graus: além disso, nenhuma estação influencia
const POTENCIA_IDW = 2.4; // quanto o peso cai com a distância

// Cada mapa e o que ele pede à API.
const MAPAS_COM_CHUVA = {
  mapa: { svg: "mapa-svg", periodo: () => ({ mes: Number($("mapa-mes").value) }) },
  cidade: { svg: "cidade-svg", periodo: () => ({ mes: Number($("mes").value) }) },
  ano: {
    svg: "ano-svg",
    // No mapa por ano faz sentido o acumulado do ano inteiro escolhido.
    periodo: () => ({ ano: Number($("ano-escolhido").value) }),
  },
};

function ligarCamadasDeChuva() {
  for (const prefixo of Object.keys(MAPAS_COM_CHUVA)) {
    const caixa = $(`${prefixo}-chuva`);
    if (caixa) caixa.addEventListener("change", () => atualizarChuva(prefixo));
  }
}

/** Liga, desliga ou redesenha a camada de chuva de um mapa. */
async function atualizarChuva(prefixo) {
  const caixa = $(`${prefixo}-chuva`);
  const tela = $(`${prefixo}-chuva-canvas`);
  const area = tela ? tela.closest(".mapa-area") : null;
  const rodape = $(`${prefixo}-chuva-nota`);
  if (!caixa || !tela || !area) return;

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);

  if (!caixa.checked) {
    // Sem a camada, o mapa volta a ser o dono da cor.
    area.classList.remove("com-chuva");
    rodape.classList.add("oculto");
    return;
  }

  const projecao = projecaoDoMapa[MAPAS_COM_CHUVA[prefixo].svg];
  if (!projecao) {
    rodape.textContent = "Desenhe o mapa primeiro para sobrepor a chuva.";
    rodape.classList.remove("oculto");
    return;
  }

  rodape.textContent = "Buscando as medições do INMET...";
  rodape.classList.remove("oculto");

  try {
    const { ano, mes } = MAPAS_COM_CHUVA[prefixo].periodo();
    const parametros = new URLSearchParams();
    if (ano) parametros.set("ano", ano);
    if (mes) parametros.set("mes", mes);

    const dados = await pedir(`/clima/chuva?${parametros}`);

    // Com a chuva por cima, o mapa embaixo vira referência geográfica: as
    // duas escalas de cor disputando a mesma área não se leem.
    area.classList.add("com-chuva");
    pintarChuva(tela, projecao, dados);
    montarLegendaDeChuva(`${prefixo}-chuva-legenda`, dados);

    rodape.textContent =
      `Chuva medida em ${dados.periodo}, por ${dados.total_estacoes} estações `
      + `automáticas do INMET · média ${dados.chuva_media_mm} mm, máxima `
      + `${dados.chuva_maxima_mm} mm. Os pontos brancos são as estações; entre `
      + `elas o valor é interpolado.`;
  } catch (erro) {
    caixa.checked = false;
    area.classList.remove("com-chuva");
    $(`${prefixo}-chuva-legenda`).classList.add("oculto");
    rodape.textContent = `Sem camada de chuva: ${erro.message}`;
  }
}

/**
 * Interpola a chuva entre as estações e pinta no canvas.
 *
 * O cálculo roda numa grade pequena (72×72) e o resultado é ampliado pelo
 * navegador, que suaviza de graça. Calcular direto nos 640×640 pixels seriam
 * 400 mil células × 600 estações — a página congelaria. Assim são 5 mil
 * células, e o degradê fica igual.
 */
function pintarChuva(tela, projecao, dados) {
  const pontos = dados.estacoes.map((e) => ({
    x: projecao.px(e.lon), y: projecao.py(e.lat), valor: e.chuva_mm,
  }));

  const passoX = projecao.largura / GRADE_CHUVA;
  const passoY = projecao.altura / GRADE_CHUVA;
  // O raio vale em graus; converte para as unidades do desenho usando a
  // própria projeção, para valer igual num mapa do país e num de estado.
  const raio = Math.abs(projecao.px(RAIO_CHUVA) - projecao.px(0));
  const raio2 = raio * raio;

  const grade = document.createElement("canvas");
  grade.width = GRADE_CHUVA;
  grade.height = GRADE_CHUVA;
  const pincel = grade.getContext("2d");
  const imagem = pincel.createImageData(GRADE_CHUVA, GRADE_CHUVA);

  for (let linha = 0; linha < GRADE_CHUVA; linha++) {
    for (let coluna = 0; coluna < GRADE_CHUVA; coluna++) {
      const x = (coluna + 0.5) * passoX;
      const y = (linha + 0.5) * passoY;

      let soma = 0, pesos = 0, maisPerto = Infinity;
      for (const ponto of pontos) {
        const dx = ponto.x - x, dy = ponto.y - y;
        const distancia2 = dx * dx + dy * dy;
        if (distancia2 > raio2) continue;
        if (distancia2 < maisPerto) maisPerto = distancia2;
        // Distância zero (a célula cai em cima da estação) daria divisão por
        // zero; o piso mantém o valor da própria estação.
        const peso = 1 / Math.pow(Math.max(distancia2, 1), POTENCIA_IDW / 2);
        soma += ponto.valor * peso;
        pesos += peso;
      }

      const posicao = (linha * GRADE_CHUVA + coluna) * 4;
      if (!pesos) continue;  // longe de tudo: fica transparente

      const cor = corDaChuva(soma / pesos, dados.escala);
      // Some suavemente na borda da área coberta, em vez de cortar reto numa
      // circunferência — aresta dura pareceria fronteira de dado, e não é.
      const proximidade = 1 - Math.min(Math.sqrt(maisPerto) / raio, 1);
      imagem.data[posicao] = cor[0];
      imagem.data[posicao + 1] = cor[1];
      imagem.data[posicao + 2] = cor[2];
      imagem.data[posicao + 3] = Math.round(235 * Math.min(proximidade * 2.2, 1));
    }
  }

  pincel.putImageData(imagem, 0, 0);

  const contexto = tela.getContext("2d");
  contexto.clearRect(0, 0, tela.width, tela.height);
  contexto.imageSmoothingEnabled = true;
  contexto.imageSmoothingQuality = "high";
  contexto.drawImage(grade, 0, 0, tela.width, tela.height);

  desenharEstacoes(contexto, pontos);
}

/** Marca onde cada estação fica: é o que separa medição de interpolação. */
function desenharEstacoes(contexto, pontos) {
  contexto.save();
  contexto.fillStyle = "rgba(255,255,255,.9)";
  contexto.strokeStyle = "rgba(20,30,45,.65)";
  contexto.lineWidth = 0.8;
  for (const ponto of pontos) {
    contexto.beginPath();
    contexto.arc(ponto.x, ponto.y, 2.1, 0, Math.PI * 2);
    contexto.fill();
    contexto.stroke();
  }
  contexto.restore();
}

function corDaChuva(milimetros, escala) {
  const faixa = escala.find(
    (f) => milimetros >= f.de && (f.ate === null || milimetros < f.ate)
  ) || escala[escala.length - 1];
  const hex = faixa.cor;
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

function montarLegendaDeChuva(idLegenda, dados) {
  const legenda = $(idLegenda);
  legenda.innerHTML =
    `<span class="legenda-titulo">chuva (${dados.unidade})</span>`
    + dados.escala.map(
        (f) => `<span><i style="background:${f.cor}"></i>${f.rotulo}</span>`
      ).join("");
  legenda.classList.remove("oculto");
}

// ---------------------------------------------------------------------------
// Animação do fenômeno escolhido
// ---------------------------------------------------------------------------
// Os dez tipos de desastre viram seis fenômenos: quatro deles são chuva com
// nomes diferentes (o que muda entre inundação e enxurrada é para onde a água
// vai, não o que cai do céu), e deslizamento e erosão são o mesmo material
// descendo. Seis animações cobrem os dez tipos sem inventar diferença visual
// onde não há diferença física.

const FENOMENO_POR_TIPO = {
  INUNDACAO: "chuva",
  ENXURRADA: "chuva",
  ALAGAMENTO: "chuva",
  CHUVAS_INTENSAS: "chuva",
  DESLIZAMENTO: "terra",
  EROSAO: "terra",
  ESTIAGEM_SECA: "seca",
  INCENDIO_FLORESTAL: "fogo",
  VENDAVAL_CICLONE: "vento",
  GRANIZO: "granizo",
};

// Quantas partículas cada fenômeno usa. Chuva precisa de muitas para virar
// chuva; rajada de vento, de poucas, senão vira listra.
const PARTICULAS = {
  chuva: 30, granizo: 20, terra: 18, fogo: 22, vento: 8, seca: 10,
};

const NOTA_ANIMACAO =
  "A animação ilustra o tipo de desastre escolhido. É decoração: não indica "
  + "onde está chovendo, nem onde vai chover.";

/**
 * Põe (ou tira) a animação de um mapa, conforme o tipo de desastre.
 *
 * É chamada no momento em que o mapa é desenhado, e não quando o seletor
 * muda: assim a animação sempre combina com os dados que estão na tela. Se
 * seguisse o seletor, apareceria chuva sobre um mapa que ainda mostra seca.
 */
function aplicarAnimacao(idCamada, tipo) {
  const camada = $(idCamada);
  if (!camada) return;

  const fenomeno = FENOMENO_POR_TIPO[tipo] || "";
  // Refazer as partículas a cada desenho reiniciaria a animação do zero e
  // custaria DOM à toa. Se o fenômeno é o mesmo, não há o que trocar.
  if (camada.dataset.fenomeno === fenomeno) return;

  camada.dataset.fenomeno = fenomeno;
  camada.innerHTML = fenomeno
    ? Array.from({ length: PARTICULAS[fenomeno] },
                 () => `<i style="${estiloDaParticula(fenomeno)}"></i>`).join("")
    : "";

  const nota = $(`${idCamada}-nota`);
  if (nota) {
    nota.textContent = fenomeno ? NOTA_ANIMACAO : "";
    nota.classList.toggle("oculto", !fenomeno);
  }
}

/** Sorteia posição, tamanho e ritmo de uma partícula. */
function estiloDaParticula(fenomeno) {
  // Sem variação, as trinta gotas cairiam em fila e no mesmo compasso — o
  // olho lê isso como listra, não como chuva.
  const n = (minimo, maximo) => (minimo + Math.random() * (maximo - minimo)).toFixed(2);

  switch (fenomeno) {
    case "chuva":
      return `left:${n(-5, 100)}%;height:${n(14, 30)}px;`
           + `animation-duration:${n(0.65, 1.25)}s;animation-delay:${n(0, 1.6)}s`;
    case "granizo":
      return `left:${n(-5, 100)}%;width:${n(3, 6)}px;height:${n(3, 6)}px;`
           + `animation-duration:${n(0.5, 0.9)}s;animation-delay:${n(0, 1.2)}s`;
    case "terra":
      return `left:${n(-5, 100)}%;width:${n(3, 7)}px;height:${n(3, 7)}px;`
           + `animation-duration:${n(2.2, 4)}s;animation-delay:${n(0, 3)}s`;
    case "fogo":
      return `left:${n(0, 100)}%;width:${n(3, 6)}px;height:${n(3, 6)}px;`
           + `--desvio:${n(-45, 45)}px;`
           + `animation-duration:${n(2.4, 4.2)}s;animation-delay:${n(0, 3.5)}s`;
    case "vento":
      return `top:${n(4, 94)}%;width:${n(90, 230)}px;`
           + `animation-duration:${n(1.8, 3.2)}s;animation-delay:${n(0, 2.6)}s`;
    case "seca":
      // Sobem do chão: começam na metade de baixo do mapa.
      return `left:${n(4, 96)}%;top:${n(35, 88)}%;height:${n(30, 60)}px;`
           + `--desvio:${n(-20, 20)}px;`
           + `animation-duration:${n(3.2, 5)}s;animation-delay:${n(0, 4)}s`;
    default:
      return "";
  }
}

/** Texto da dica no mapa de risco: uma previsão do modelo. */
function dicaDeRisco(info) {
  return `<strong>${info.municipio}</strong> — ${info.uf}<br>`
       + `risco ${info.nivel_risco}<br>`
       + `chance de ser grave: ${porcento(info.probabilidade_alto)}`;
}

/**
 * Desenha um conjunto de municípios num SVG, com a cor que a API mandou.
 *
 * Serve aos três mapas — país, cidade e ano — porque não sabe o que a cor
 * significa: quem chama decide o que entra em `porMunicipio` e como a dica é
 * escrita. O enquadramento é recalculado a cada chamada, então um estado ou
 * uma região preenchem a tela em vez de virar um ponto no meio do Brasil.
 */
function renderizarSvg(idSvg, idDica, feicoes, porMunicipio, codigoEmFoco = null,
                       descrever = dicaDeRisco) {
  const svg = $(idSvg);
  const [, , LARGURA, ALTURA] = svg.getAttribute("viewBox").split(" ").map(Number);
  const MARGEM = 12;

  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  const visitar = (coords, aplicar) => {
    if (typeof coords[0] === "number") aplicar(coords);
    else coords.forEach((c) => visitar(c, aplicar));
  };
  feicoes.forEach((f) => visitar(f.geometry.coordinates, ([lon, lat]) => {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }));

  const larguraGeo = Math.max(maxLon - minLon, 1e-6);
  const alturaGeo = Math.max(maxLat - minLat, 1e-6);
  const escala = Math.min((LARGURA - MARGEM * 2) / larguraGeo,
                          (ALTURA - MARGEM * 2) / alturaGeo);
  const deslocaX = (LARGURA - larguraGeo * escala) / 2;
  const deslocaY = (ALTURA - alturaGeo * escala) / 2;

  const px = (lon) => (lon - minLon) * escala + deslocaX;
  // O y do SVG cresce para baixo; a latitude cresce para cima.
  const py = (lat) => (maxLat - lat) * escala + deslocaY;

  const anelParaPath = (anel) =>
    "M" + anel.map(([lon, lat]) => `${px(lon).toFixed(1)},${py(lat).toFixed(1)}`)
              .join("L") + "Z";

  const partes = [];
  feicoes.forEach((f) => {
    const codigo = f.properties.codigo_ibge;
    const info = porMunicipio.get(codigo);
    const g = f.geometry;
    const poligonos = g.type === "Polygon" ? [g.coordinates] : g.coordinates;

    const d = poligonos.map((p) => p.map(anelParaPath).join("")).join("");
    if (!d) return;

    if (info) {
      const foco = codigo === codigoEmFoco ? " foco" : "";
      partes.push(
        `<path d="${d}" fill="${info.cor}" class="${foco.trim()}" data-ibge="${codigo}"></path>`
      );
    } else {
      partes.push(`<path d="${d}" class="sem-dado"></path>`);
    }
  });

  svg.innerHTML = partes.join("");

  // Um único listener no SVG, em vez de um por município — com 5.570
  // elementos, a diferença de desempenho trava a página.
  svg.onmousemove = (evento) => {
    const alvo = evento.target.closest("path[data-ibge]");
    const dica = $(idDica);
    if (!alvo) { dica.classList.add("oculto"); return; }

    const info = porMunicipio.get(Number(alvo.dataset.ibge));
    dica.innerHTML = descrever(info);
    const area = svg.getBoundingClientRect();
    dica.style.left = `${Math.min(evento.clientX - area.left + 14, area.width - 250)}px`;
    dica.style.top = `${evento.clientY - area.top + 14}px`;
    dica.classList.remove("oculto");
  };
  svg.onmouseleave = () => $(idDica).classList.add("oculto");

  // A projeção fica guardada para a camada de chuva poder desenhar sobre
  // exatamente o mesmo enquadramento. Recalculá-la por fora daria um mapa
  // deslocado toda vez que o recorte mudasse (um estado, uma região).
  projecaoDoMapa[idSvg] = { px, py, largura: LARGURA, altura: ALTURA };
  return projecaoDoMapa[idSvg];
}

// Enquadramento de cada mapa, preenchido por `renderizarSvg`.
const projecaoDoMapa = {};

function montarLegenda(idLegenda, resumo) {
  const legenda = $(idLegenda);
  legenda.innerHTML =
    ["baixo", "medio", "alto"].map((nivel) =>
      `<span><i style="background:${CORES[nivel]}"></i>${nivel}`
      + ` (${resumo[nivel].toLocaleString("pt-BR")})</span>`
    ).join("")
    + amostraSemDado("sem histórico deste tipo");
  legenda.classList.remove("oculto");
}

/* A cor de "sem dado" vem da variável do CSS, e não de um hexadecimal escrito
   aqui: assim ela acompanha o tema escuro junto com o mapa que ela explica. */
function amostraSemDado(rotulo) {
  return `<span><i style="background:var(--cinza-dado)"></i>${rotulo}</span>`;
}

// ---------------------------------------------------------------------------
// Mapa por ano — o que já aconteceu
// ---------------------------------------------------------------------------
// Este mapa não passa pelo modelo: mostra o registro do Atlas, ano a ano. A
// diferença importa na leitura, e é por isso que a escala de cor é outra —
// aqui a cor conta ocorrências, não estima risco. Duas escalas iguais para
// coisas diferentes seria o jeito mais fácil de alguém confundir uma previsão
// com um fato.

function prepararMapaDoAno() {
  const tipo = $("ano-tipo");
  tipo.add(new Option("Todos os tipos", ""));
  TIPOS_DESASTRE.forEach((t) => tipo.add(new Option(formatarTipo(t), t)));

  const uf = $("ano-uf");
  uf.add(new Option("Brasil inteiro", ""));
  UFS.forEach((sigla) => uf.add(new Option(sigla, sigla)));

  $("form-ano").addEventListener("submit", (evento) => {
    evento.preventDefault();
    desenharMapaDoAno(Number($("ano-escolhido").value), tipo.value, uf.value);
  });
}

async function carregarAnos() {
  const seletor = $("ano-escolhido");
  try {
    const dados = await pedir("/historico/anos");
    // Do mais recente para o mais antigo: é o que quase todo mundo procura
    // primeiro, e evita rolar 35 opções até o fim da lista.
    [...dados.anos].reverse().forEach((a) => {
      seletor.add(new Option(
        `${a.ano} — ${a.ocorrencias.toLocaleString("pt-BR")} ocorrências`, a.ano
      ));
    });
    seletor.value = String(dados.ultimo_ano);
  } catch (erro) {
    $("ano-estado").textContent =
      `Não foi possível carregar os anos disponíveis: ${erro.message}`;
    $("ano-botao").disabled = true;
  }
}

async function desenharMapaDoAno(ano, tipo = "", ufEscolhida = "") {
  const botao = $("ano-botao");
  botao.disabled = true;
  botao.textContent = "Desenhando...";
  $("ano-estado").textContent = malhaCache
    ? "Reunindo as ocorrências do ano..."
    : "Baixando as fronteiras dos municípios (3 MB, só na primeira vez)...";

  try {
    if (!malhaCache) malhaCache = await pedir("/mapa/malha");

    const filtro = tipo ? `?grupo_desastre=${tipo}` : "";
    const dados = await pedir(`/historico/ano/${ano}${filtro}`);

    const soDoEstado = (codigo) => !ufEscolhida || ufDoCodigo(codigo) === ufEscolhida;
    const feicoes = malhaCache.features.filter(
      (f) => soDoEstado(f.properties.codigo_ibge)
    );
    const doMapa = dados.municipios.filter((m) => soDoEstado(m.codigo_ibge));
    const porMunicipio = new Map(doMapa.map((m) => [m.codigo_ibge, m]));

    renderizarSvg("ano-svg", "ano-dica", feicoes, porMunicipio, null,
                  dicaDeOcorrencias);
    // Com "todos os tipos" não há um fenômeno só para ilustrar, e a camada
    // fica vazia — misturar chuva com fogo não descreveria nada.
    aplicarAnimacao("ano-animacao", tipo);
    atualizarChuva("ano");

    mostrarNumerosDoAno(dados, doMapa, ufEscolhida);
    montarLegendaDoAno(dados.legenda);
    mostrarMesesDoAno(dados);
    mostrarTiposDoAno(dados);

    const oQue = tipo ? formatarTipo(tipo) : "Desastres de todos os tipos";
    const onde = ufEscolhida ? `em ${ufEscolhida}` : "no Brasil";
    $("ano-estado").textContent =
      `${oQue} registrados em ${ano}, ${onde} · `
      + `${doMapa.length.toLocaleString("pt-BR")} municípios atingidos.`;
  } catch (erro) {
    $("ano-estado").textContent = `Não foi possível montar o mapa: ${erro.message}`;
    ["ano-numeros", "ano-legenda", "ano-meses", "ano-tipos"]
      .forEach((id) => $(id).classList.add("oculto"));
    $("ano-svg").innerHTML = "";
    // Sem isto, a chuva continuaria caindo sobre um mapa vazio e uma
    // mensagem de erro.
    aplicarAnimacao("ano-animacao", "");
  } finally {
    botao.disabled = false;
    botao.textContent = "Mostrar";
  }
}

function dicaDeOcorrencias(info) {
  const tipos = (info.tipos || []).map(formatarTipo).join(", ");
  const linhas = [
    `<strong>${info.municipio}</strong> — ${info.uf}`,
    `${info.ocorrencias} ocorrência(s) no ano`,
  ];
  if (tipos) linhas.push(tipos);
  if (info.mortos) linhas.push(`${info.mortos} morto(s)`);
  if (info.afetados) {
    linhas.push(`${info.afetados.toLocaleString("pt-BR")} afetados`);
  }
  return linhas.join("<br>");
}

function montarLegendaDoAno(faixas) {
  $("ano-legenda").innerHTML =
    faixas.map((f) => `<span><i style="background:${f.cor}"></i>${f.rotulo}</span>`)
      .join("")
    + amostraSemDado("nenhuma ocorrência registrada");
  $("ano-legenda").classList.remove("oculto");
}

function mostrarNumerosDoAno(dados, doMapa, ufEscolhida) {
  // Com o mapa filtrado por estado, os totais do país deixariam de descrever o
  // que está na tela. Nesse caso os números são recontados sobre o recorte.
  const soma = (campo) => doMapa.reduce((total, m) => total + m[campo], 0);
  const recorte = Boolean(ufEscolhida);

  const numeros = [
    [recorte ? soma("ocorrencias") : dados.total_ocorrencias, "ocorrências"],
    [recorte ? doMapa.length : dados.municipios_atingidos, "municípios atingidos"],
    [recorte ? soma("mortos") : dados.mortos, "mortos"],
    [recorte ? soma("afetados") : dados.afetados, "pessoas afetadas"],
    [recorte ? soma("reconhecidos") : dados.reconhecidos, "emergências reconhecidas"],
  ];

  $("ano-numeros").innerHTML = numeros.map(([valor, rotulo]) =>
    `<div class="numero"><strong>${valor.toLocaleString("pt-BR")}</strong>`
    + `<span>${rotulo}</span></div>`
  ).join("");
  $("ano-numeros").classList.remove("oculto");
}

function mostrarMesesDoAno(dados) {
  const maximo = Math.max(...dados.por_mes, 1);
  $("ano-grafico").innerHTML = dados.por_mes.map((valor, i) =>
    `<div class="coluna" title="${MESES[i]}: ${valor} ocorrência(s)">
       <span class="coluna-valor">${valor}</span>
       <div class="coluna-barra" style="height:${(valor / maximo) * 100}%"></div>
       <span class="coluna-mes">${MESES[i].slice(0, 3)}</span>
     </div>`
  ).join("");
  $("ano-meses").classList.remove("oculto");
}

function mostrarTiposDoAno(dados) {
  const tabela = $("ano-tabela-tipos");
  tabela.innerHTML = "<tr><th>Tipo</th><th>Ocorrências</th><th>Municípios</th>"
                   + "<th>Mortos</th><th>Afetados</th></tr>";

  dados.por_tipo.forEach((t) => {
    const linha = tabela.insertRow();
    linha.insertCell().textContent = formatarTipo(t.grupo_desastre);
    [t.ocorrencias, t.municipios, t.mortos, t.afetados].forEach((valor) => {
      const celula = linha.insertCell();
      celula.className = "numero";
      celula.textContent = Number(valor).toLocaleString("pt-BR");
    });
  });
  $("ano-tipos").classList.remove("oculto");
}

// ---------------------------------------------------------------------------
// Menu e tema
// ---------------------------------------------------------------------------

/**
 * Liga o menu do topo.
 *
 * Boa parte das seções começa escondida e só aparece depois de uma consulta.
 * Um link para uma seção invisível não leva a lugar nenhum, então os itens
 * acompanham as seções: um observador avisa quando `.oculto` sai ou entra, e
 * o menu se ajusta sozinho — sem precisar lembrar de chamá-lo em cada ponto
 * do código que revela uma seção.
 */
function ligarMenu() {
  const itens = [...document.querySelectorAll("#menu-itens a")].map((link) => ({
    link,
    secao: document.querySelector(link.getAttribute("href")),
  })).filter((item) => item.secao);

  const sincronizar = () => {
    itens.forEach(({ link, secao }) => {
      link.parentElement.classList.toggle("oculto",
        secao.classList.contains("oculto"));
    });
  };

  const observador = new MutationObserver(sincronizar);
  itens.forEach(({ secao }) => {
    observador.observe(secao, { attributes: true, attributeFilter: ["class"] });
  });
  sincronizar();

  // Marca no menu a seção que está sendo lida. A margem superior desconta a
  // altura do próprio menu, senão a seção "ativa" seria sempre a que está
  // escondida atrás dele.
  const espia = new IntersectionObserver((entradas) => {
    entradas.forEach((entrada) => {
      if (!entrada.isIntersecting) return;
      itens.forEach(({ link, secao }) => {
        link.classList.toggle("ativo", secao === entrada.target);
      });
    });
  }, { rootMargin: "-64px 0px -70% 0px", threshold: 0 });

  itens.forEach(({ secao }) => espia.observe(secao));
}

/**
 * Liga o botão de tema.
 *
 * O tema já foi aplicado pelo script no <head>, antes da primeira pintura.
 * Aqui só ficam o botão e a memória da escolha.
 */
function ligarTema() {
  const botao = $("botao-tema");

  const aplicar = (tema, guardar) => {
    document.documentElement.dataset.tema = tema;
    const escuro = tema === "escuro";
    botao.setAttribute("aria-pressed", String(escuro));
    $("botao-tema").querySelector(".botao-tema-texto").textContent =
      escuro ? "Modo claro" : "Modo escuro";
    if (guardar) {
      try {
        localStorage.setItem("fecart-tema", tema);
      } catch (e) {
        /* sem localStorage: o tema vale só para esta visita */
      }
    }
  };

  aplicar(document.documentElement.dataset.tema || "claro", false);

  botao.addEventListener("click", () => {
    const atual = document.documentElement.dataset.tema;
    aplicar(atual === "escuro" ? "claro" : "escuro", true);
  });
}

async function mostrarOddsRatio() {
  let dados;
  try {
    dados = await pedir("/modelo/odds-ratio?analise=gravidade");
  } catch (erro) {
    return; // modelo treinado sem a análise; a seção simplesmente não aparece
  }

  // Só entram os efeitos confiáveis e estatisticamente distinguíveis de 1.
  const variaveis = dados.variaveis
    .filter((v) => v.significativo && v.confiavel !== false)
    .slice(0, 10);
  if (!variaveis.length) return;

  // Escala centrada em 1 e simétrica em log: um OR de 4 e um de 0,25 têm o
  // mesmo tamanho de barra, em lados opostos. É a leitura correta, porque
  // dobrar e cortar pela metade são efeitos equivalentes.
  const maiorLog = Math.max(...variaveis.map((v) => Math.abs(Math.log(v.odds_ratio))));

  const caixa = $("odds");
  caixa.innerHTML = "";

  variaveis.forEach((v) => {
    const proporcao = Math.abs(Math.log(v.odds_ratio)) / maiorLog;
    const largura = proporcao * 50; // metade do trilho é 100% da escala
    const aumenta = v.odds_ratio >= 1;
    const posicao = aumenta ? `left:50%; width:${largura}%`
                            : `right:50%; width:${largura}%`;

    const linha = document.createElement("div");
    linha.className = "odds-linha";
    linha.innerHTML =
      `<span class="odds-nome">${nomeVariavel(v.variavel)}</span>
       <div class="odds-trilho">
         <div class="odds-centro"></div>
         <div class="odds-barra ${aumenta ? "aumenta" : "reduz"}" style="${posicao}"></div>
       </div>
       <span class="odds-valor">${v.odds_ratio.toFixed(2).replace(".", ",")}x
         <span class="odds-ic">${v.ic95_inferior.toFixed(2)}–${v.ic95_superior.toFixed(2)}</span>
       </span>`;
    linha.title = `${nomeVariavel(v.variavel)}: multiplica a chance por `
                + `${v.odds_ratio.toFixed(2)} (IC 95%: ${v.ic95_inferior.toFixed(2)} a `
                + `${v.ic95_superior.toFixed(2)})`;
    caixa.appendChild(linha);
  });

  $("odds-rodape").textContent =
    `Regressão logística sobre ${dados.n_amostras.toLocaleString("pt-BR")} `
    + `observações (AUC ${dados.auc.toFixed(3).replace(".", ",")}). `
    + `Variáveis numéricas medidas por desvio-padrão.`;

  $("secao-odds").classList.remove("oculto");
}

function nomeVariavel(chave) {
  if (chave.startsWith("grupo_desastre_")) {
    return "Ser " + formatarTipo(chave.replace("grupo_desastre_", "")).toLowerCase();
  }
  if (chave.startsWith("regiao_")) {
    return "Região " + chave.replace("regiao_", "");
  }
  return ROTULOS[chave] || formatarTipo(chave);
}

async function carregarHistorico(codigoIbge) {
  try {
    const h = await pedir(`/municipios/${codigoIbge}/historico`);

    $("historico-resumo").textContent =
      `${h.total_ocorrencias} ocorrências registradas entre `
      + `${h.periodo.primeiro_ano} e ${h.periodo.ultimo_ano}.`;

    const tabela = $("tabela-historico");
    tabela.innerHTML =
      "<tr><th>Tipo</th><th>Ocorrências</th><th>Mortos</th>"
      + "<th>Afetados</th><th>Último</th></tr>";

    h.por_tipo.forEach((t) => {
      const linha = tabela.insertRow();
      linha.insertCell().textContent = formatarTipo(t.grupo_desastre);
      [t.ocorrencias, t.mortos, t.afetados, t.ultimo_ano].forEach((valor, i) => {
        const celula = linha.insertCell();
        celula.className = "numero";
        // O último ano é um ano, não uma contagem: não leva separador de milhar.
        celula.textContent = i === 3 ? valor : Number(valor).toLocaleString("pt-BR");
      });
    });

    $("secao-historico").classList.remove("oculto");
  } catch (erro) {
    $("secao-historico").classList.add("oculto");
  }
}

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

async function pedir(caminho, corpo = null) {
  const opcoes = corpo
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo) }
    : {};
  const resposta = await fetch(API + caminho, opcoes);

  if (!resposta.ok) {
    let detalhe = `erro ${resposta.status}`;
    try {
      const json = await resposta.json();
      if (json.detail) detalhe = typeof json.detail === "string"
        ? json.detail : JSON.stringify(json.detail);
    } catch (e) { /* resposta sem corpo JSON */ }
    throw new Error(detalhe);
  }
  return resposta.json();
}

function mostrarAviso(texto, ehErro) {
  const caixa = $("aviso-modelo");
  caixa.textContent = texto;
  caixa.className = ehErro ? "aviso erro" : "aviso";
}

function formatarTipo(chave) {
  return String(chave).replaceAll("_", " ").toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
}

function porcento(valor) {
  return (valor * 100).toFixed(1).replace(".", ",") + "%";
}

function formatarData(iso) {
  if (!iso) return "data desconhecida";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString("pt-BR");
}

function formatarValor(chave, valor) {
  if (chave === "ja_ocorreu") return valor > 0 ? "sim" : "não";
  if (chave === "meses_desde_ultima_ocorrencia" && valor < 0) return "nunca ocorreu";
  if (chave === "prejuizo_historico_log") {
    // Desfaz o log para mostrar um número que faz sentido para quem lê.
    return "R$ " + Math.round(Math.expm1(valor)).toLocaleString("pt-BR");
  }
  if (chave === "anos_de_historico") return valor.toFixed(1).replace(".", ",");
  return Number(valor).toLocaleString("pt-BR");
}

iniciar();
