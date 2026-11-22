
# Design — génération vidéo paramétrable

Concerne le cahier des charges (annexe A) (spec de l'appli) et le modèle de prompt (annexe B) (modèle de prompt du montage).

## Pourquoi
Sur un « week-end entre copains », la musique générée était trop mélancolique. Cause : le prompt vidéo imposait une bande-son figée (« Fin : musique plus émotionnelle ») et un scénario écrit pour un week-end à la mer. L'organisateur ne pouvait régler que la durée.

## Objectifs
- Choisir à la génération le ton, la musique, l'évolution de la bande-son, la fin, le rythme, les effets et le format.
- Pré-remplir ces réglages selon le type d'événement, pour ne pas partir d'un formulaire vide.
- Rendre la musique prévisible : on écoute avant de générer, et on peut la changer après.

## Non-objectifs
- Composer de la musique par IA.
- Proposer un éditeur vidéo plan par plan.

## Anti-objectifs (échec même si ça marche)
- Un formulaire si long qu'on le remplit au hasard sur mobile.
- Une musique triste sur un événement festif alors que les réglages disaient « festif ».

## Approches envisagées
| Option | Principe | Compromis |
|---|---|---|
| A · Ambiances prêtes | 4 ambiances en un tap | Simple, mais pas de réglage fin |
| B · Réglages libres | Tous les réglages visibles | Contrôle total, risque de formulaire lourd |
| C · Hybride | Ambiance proposée + « Personnaliser » | Rapide, mais réglages cachés |

**Choix : B, avec plus de choix** (décision de l'organisateur). Le risque de lourdeur est compensé par des sections, un pré-remplissage selon le type d'événement et des préréglages enregistrables (choix de Claude, validés sur maquette).

## Décisions
- **Écran Génération en 4 sections** : Histoire, Musique, Montage, Format (liste complète des choix dans le cahier des charges (annexe A), section « Réglages vidéo »).
- **Ton : 2 choix maximum** parmi 10.
- **Un seul ton pour le texte et la vidéo** (décision de l'organisateur, 2026-11-21) : il est choisi à la création de l'événement, pré-rempli selon le type, et modifiable à la génération. Le modifier change le ton de l'événement entier. L'ancien ton du compte rendu (« souvenir détendu », « bilan sportif »…) disparaît.
- **Valeurs par défaut selon le type d'événement** (10 types). Elles sont modifiables à la génération.
- **Préréglages** : « Enregistrer comme préréglage », réutilisables d'un événement à l'autre.
- **Musique tirée d'un catalogue local de morceaux libres de droits étiquetés** (genre, énergie 1-5, humeur, BPM, licence). Les réglages filtrent ce catalogue ; l'IA n'interprète pas librement le mot « émotionnel ».
- **Règle anti-mélancolie** : pas de morceau d'humeur « mélancolique » ou « triste », sauf si le ton contient Tendre ou Nostalgique. Seule exception : la séquence finale quand la fin est Touchante ou l'évolution « Festif puis émotion ».
- **Pré-écoute de 15 s** + « Autre titre » avant de générer.
- **Relecture : « Changer la musique »** remplace la bande-son sans refaire la sélection des plans.
- **le modèle de prompt (annexe B) devient un modèle** : un bloc de paramètres en tête, puis des consignes qui dépendent de chaque réglage. Il reste utilisable seul, hors de l'appli.

## Décisions prises au lancement du développement (2026-11-21)
- **Source des musiques** : une bibliothèque libre (Incompetech, Kevin MacLeod, CC BY 4.0, avec un crédit ajouté automatiquement en fin de film), **plus** l'ajout de ses propres MP3 dans l'appli. La liste d'environ 40 morceaux est validée par l'organisateur avant tout téléchargement.
- **Deux PR** : PR 1 « réglages et musique » (tons, types, réglages Histoire/Musique/Format de base, catalogue, règle anti-mélancolie, pré-écoute, changer la musique, ajout de musiques) ; PR 2 « effets de montage » (rythme, ralentis, accélérés, arrêts sur image, effets humoristiques, style des titres, cadrage, évolution multi-morceaux, préréglages).
- La cause du problème initial : le seul morceau du ton « détendu » (`music/detendu.mp3`, synthétisé, 84 BPM, accords maj7/m7) sonne nostalgique.

## Laissé au développeur
- Format de stockage du catalogue et des préréglages.
- Choix des morceaux du catalogue initial (environ 40, en couvrant chaque genre et chaque niveau d'énergie), avec une licence vérifiée pour chacun.
- Recalage des coupes sur les temps forts quand la musique change en relecture (si c'est faisable simplement).

## Annexe A — Réglages vidéo (extrait du cahier des charges)

**Réglages vidéo (écran Génération) :**

Tous les réglages sont visibles et rangés en 4 sections repliables. Ils sont pré-remplis selon le type d'événement.

| Section | Réglage | Choix |
|---|---|---|
| Histoire | Type d'événement | Week-end copains · Course, trail · Anniversaire · Mariage · Vacances famille · Road-trip · Rando, montagne · Soirée · EVG, EVJF · Autre (texte libre) |
| Histoire | Ton (2 max) | Drôle · Festif · Épique · Tendre · Chill · Nostalgique · Motivant · Décalé · Cinéma · Documentaire — ton de l'événement, partagé avec le compte rendu écrit ; le modifier ici le change pour l'événement, donc aussi pour le texte à la prochaine génération |
| Histoire | Fin du film | Festive · Bêtisier · Touchante · Épique |
| Musique | Genres (plusieurs) | Pop · Électro · Rock · Indie · Hip-hop · Funk, disco · Tropical · Folk · Lo-fi · Années 80 · Chanson FR · Jazz · Piano · Orchestral |
| Musique | Énergie | curseur 1 (calme) à 5 (survolté) |
| Musique | Évolution | Constante · Montée progressive · Calme puis explosion · Festif puis émotion |
| Musique | Mélange | curseur 0 (sons réels) à 100 (musique), défaut 55 |
| Montage | Rythme | Posé · Dynamique · Clip nerveux |
| Montage | Effets (interrupteurs) | Ralentis · Accélérés · Arrêts sur image · Effets humoristiques · Sous-titres des citations |
| Montage | Style des titres | Carnet manuscrit · Sobre · Pop coloré · Aucun |
| Format | Durée | 30 s · 1 min · 2 min · 3 min · 5 min (défaut 2 min) |
| Format | Cadrage | Horizontal 16:9 · Vertical 9:16 · Carré 1:1 (défaut 16:9) |
| Format | Consignes en plus | texte libre facultatif (ex. « Finir sur le plongeon de Léo ») |

Valeurs par défaut selon le type d'événement (effets tous activés, sauf « Effets humoristiques » désactivé pour Mariage) :

| Type | Ton | Genres | Énergie | Évolution | Fin | Rythme |
|---|---|---|---|---|---|---|
| Week-end copains | Drôle + Festif | Pop, Électro, Funk | 4 | Montée progressive | Festive | Dynamique |
| Course, trail | Épique + Motivant | Rock, Électro, Orchestral | 5 | Calme puis explosion | Épique | Clip nerveux |
| Anniversaire | Festif + Tendre | Pop, Funk, Chanson FR | 4 | Festif puis émotion | Touchante | Dynamique |
| Mariage | Tendre + Cinéma | Piano, Folk, Orchestral | 3 | Montée progressive | Touchante | Posé |
| Vacances famille | Chill + Tendre | Folk, Pop, Tropical | 3 | Constante | Touchante | Posé |
| Road-trip | Chill + Décalé | Indie, Rock, Années 80 | 4 | Constante | Festive | Dynamique |
| Rando, montagne | Épique + Chill | Folk, Orchestral, Indie | 3 | Montée progressive | Épique | Posé |
| Soirée | Festif + Drôle | Électro, Hip-hop, Funk | 5 | Constante | Bêtisier | Clip nerveux |
| EVG, EVJF | Drôle + Décalé | Pop, Années 80, Funk | 5 | Montée progressive | Bêtisier | Clip nerveux |
| Autre | Drôle + Chill | Pop, Indie | 3 | Montée progressive | Festive | Dynamique |

- **Pré-écoute** : en bas de l'écran, le morceau proposé pour ces réglages, avec « Écouter 15 s » et « Autre titre ».
- **Préréglages** : « Enregistrer comme préréglage » (nom libre) ; les préréglages sont proposés en haut de l'écran Génération pour tous les événements suivants.
- **Règle anti-mélancolie** : aucun morceau d'humeur « mélancolique » ou « triste », sauf si le ton contient Tendre ou Nostalgique. Seule exception : la séquence finale quand la fin est « Touchante » ou l'évolution « Festif puis émotion ».
- Les réglages remplissent le modèle de prompt le modèle de prompt (annexe B), fourni avec ce cahier des charges ; Claude s'en sert pour produire le plan de montage.


## Annexe B — Modèle de prompt du montage

### Paramètres

```
Nom de l'événement : {{nom}}
Type d'événement : {{type}}            (Week-end copains | Course, trail | Anniversaire | Mariage | Vacances famille | Road-trip | Rando, montagne | Soirée | EVG, EVJF | Autre : {{type_libre}})
Lieu / décor : {{lieu}}                (ex. bord de mer, montagne, ville, campagne)
Ton (2 max) : {{ton}}                  (Drôle | Festif | Épique | Tendre | Chill | Nostalgique | Motivant | Décalé | Cinéma | Documentaire)
Fin du film : {{fin}}                  (Festive | Bêtisier | Touchante | Épique)
Genres musicaux : {{genres}}           (Pop | Électro | Rock | Indie | Hip-hop | Funk, disco | Tropical | Folk | Lo-fi | Années 80 | Chanson FR | Jazz | Piano | Orchestral)
Énergie musicale : {{energie}}/5       (1 = calme, 5 = survolté)
Évolution de la musique : {{evolution}} (Constante | Montée progressive | Calme puis explosion | Festif puis émotion)
Mélange sons réels / musique : {{mix}}/100  (0 = sons réels seuls, 100 = musique seule)
Rythme du montage : {{rythme}}         (Posé | Dynamique | Clip nerveux)
Ralentis : {{ralentis}}                (oui | non)
Accélérés : {{acceleres}}              (oui | non)
Arrêts sur image : {{arrets}}          (oui | non)
Effets humoristiques : {{effets_humour}} (oui | non)
Sous-titres des citations : {{sous_titres}} (oui | non)
Style des titres : {{style_titres}}    (Carnet manuscrit | Sobre | Pop coloré | Aucun)
Durée : {{duree}}                      (30 s | 1 min | 2 min | 3 min | 5 min)
Cadrage : {{cadrage}}                  (Horizontal 16:9 | Vertical 9:16 | Carré 1:1)
Consignes en plus : {{consignes}}
```

---

### Prompt

Réalise un véritable aftermovie de l'événement « {{nom}} » ({{type}}, {{lieu}}). Le ton est **{{ton}}**. L'esthétique doit rester naturelle et authentique. Évite absolument l'effet diaporama.

Le film doit faire ressortir ce qui compte le plus pour ce type d'événement : les personnes, leur complicité, les moments partagés et l'ambiance du lieu ({{lieu}}).

#### 1. Ton

Applique le ou les tons choisis à la sélection des plans, au rythme, aux titres et à la musique :

| Ton | Ce que ça change |
|---|---|
| Drôle | Mise en avant des fous rires, maladresses et répliques ; timing comique |
| Festif | Énergie de groupe, danse, célébrations ; couleurs vives |
| Épique | Plans larges, montée en tension, ralentis sur les temps forts |
| Tendre | Regards, gestes, accolades ; rythme plus doux |
| Chill | Lumière, paysages, moments calmes ; pas de surenchère |
| Nostalgique | Plans contemplatifs, grain chaleureux ; réservé aux souvenirs « doux-amers » |
| Motivant | Effort, dépassement, encouragements ; coupes franches |
| Décalé | Absurde assumé, situations insolites, effets inattendus |
| Cinéma | Cadrages soignés, transitions lentes, titre final travaillé |
| Documentaire | Chronologie fidèle, sons réels, peu d'effets |

Si deux tons sont choisis, le premier domine et le second nuance.

#### 2. Séquences

Construis une narration fluide en suivant les séquences du type d'événement ci-dessous. Pour 30 s et 1 min, fusionne-les en 3 ou 4 séquences. Pour 5 min, tu peux en dédoubler une si les médias le justifient. N'invente jamais une séquence qui n'a pas d'images.

| Type | Séquences |
|---|---|
| Week-end copains | Les retrouvailles · Le décor · La vie entre copains · Les moments cultes · Le best-of · La conclusion |
| Course, trail | Avant le départ · Le départ · L'effort · Les visages de la course · L'arrivée · Le podium et la fête |
| Anniversaire | L'arrivée des invités · Les préparatifs · La fête · Le gâteau et les surprises · Le best-of · Le mot de la fin |
| Mariage | Les préparatifs · La cérémonie · Les émotions · La fête · Le best-of · Le final |
| Vacances famille | Le départ · Les lieux · Les journées · Les moments cultes · Le best-of · Le retour |
| Road-trip | Le départ · La route · Les étapes · Galères et fous rires · Le best-of · L'arrivée |
| Rando, montagne | Le départ · L'ascension · Les panoramas · Les pauses · Le sommet · La descente |
| Soirée | Les préparatifs · Les arrivées · La fête · Les moments cultes · Le best-of · Fin de soirée |
| EVG, EVJF | L'accueil · Les défis · La vie de groupe · Les moments cultes · Le best-of · La conclusion |
| Autre | 4 à 6 séquences déduites des médias, dans l'ordre chronologique |

La séquence « Les moments cultes » (ou son équivalent) reçoit les effets humoristiques si `{{effets_humour}}` = oui.

#### 3. Fin du film

| Fin | Consigne |
|---|---|
| Festive | Terminer sur l'énergie du groupe (cri, saut, toast, danse) ; musique au plus fort, puis titre final |
| Bêtisier | Après le titre final, enchaîner 15 à 30 s de ratés et fous rires, sons réels en avant |
| Touchante | Ralentir, plan de groupe ou regard complice, musique plus douce ; titre final évocateur |
| Épique | Dernier temps fort (arrivée, sommet, panorama) en ralenti, musique au sommet, puis titre final |

#### 4. Montage

- Sélectionne les médias les plus intéressants et évite les doublons. Ne cherche pas à tout utiliser.
- Privilégie les vidéos lorsqu'elles apportent du mouvement ou de l'émotion.
- Alterne plans larges, portraits, scènes collectives et détails.
- Rythme `{{rythme}}` :
  - Posé : plans de 3 à 5 s, transitions fondues ;
  - Dynamique : plans de 1,5 à 3 s, coupes sur les temps de la musique ;
  - Clip nerveux : plans de 0,5 à 1,5 s, coupes franches, quelques plans plus longs pour respirer.
- Synchronise les changements de plans avec la musique.
- Ralentis : {{ralentis}}. Accélérés : {{acceleres}}. Arrêts sur image : {{arrets}}. Effets humoristiques : {{effets_humour}}. N'utilise que les effets marqués « oui », et seulement quand les images s'y prêtent.
- Titres de séquence en style `{{style_titres}}` (aucun titre si « Aucun »). Sous-titres des citations : {{sous_titres}}.
- Cadrage `{{cadrage}}` : recadre intelligemment en gardant les visages entiers, sans déformation. Si un plan ne peut pas être recadré sans couper l'essentiel, utilise un fond flou plutôt qu'un étirement.
- Durée cible : {{duree}} (±5 %).
- Respecte les proportions, les visages et l'apparence naturelle des personnes. Ne déforme jamais les images et ne crée aucune scène fictive.

#### 5. Bande-son

**Genres autorisés** : {{genres}}. **Énergie** : {{energie}}/5 (tolérance ±1).

Évolution `{{evolution}}` :
- Constante : même énergie du début à la fin, un ou deux morceaux enchaînés ;
- Montée progressive : énergie −1 au début, cible au milieu, +1 sur le best-of ;
- Calme puis explosion : début calme (énergie 1 ou 2), bascule franche sur un temps fort, puis énergie maximale ;
- Festif puis émotion : énergie cible jusqu'au best-of, puis morceau plus doux sur la seule séquence finale.

**Règle anti-mélancolie** : n'utilise aucune musique mélancolique ou triste, sauf si le ton contient Tendre ou Nostalgique. Seule exception : la séquence finale quand la fin est « Touchante » ou l'évolution « Festif puis émotion ».

Mélange `{{mix}}/100` : en dessous de 40, les sons réels (rires, conversations, vagues, ambiance) passent devant et la musique baisse sous les paroles. Au-dessus de 60, la musique domine et les sons réels ne ressortent que sur les répliques marquantes. Sur les séquences humoristiques, garde toujours les sons originaux audibles.

Utilise uniquement des musiques libres de droits ou autorisées (dans l'appli : uniquement des morceaux du catalogue).

#### 6. Consignes en plus

{{consignes}}

(Si ce champ est vide, ignore cette section. S'il contredit un réglage, les consignes en plus l'emportent.)

### Exigences finales

Le montage doit correspondre au ton choisi ({{ton}}) et rester authentique plutôt que techniquement sophistiqué. On doit avoir l'impression de revivre l'événement.

**Livrable** : utilisé seul, réalise directement le film monté, exporté et prêt à partager, sans t'arrêter à un scénario ou à un storyboard. Dans l'appli, produis le plan de montage complet (ordre des extraits, points d'entrée et de sortie, effets, titres, sous-titres, choix et placement des morceaux du catalogue), que FFmpeg exécute.
