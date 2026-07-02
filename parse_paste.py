# -*- coding: utf-8 -*-
"""Parse le texte collé SeLoger et insère dans listings_chamonix.db"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import re, sqlite3, json
from pathlib import Path
from datetime import date

DB  = Path(__file__).parent / "dvf" / "listings_chamonix.db"
TODAY = date.today().isoformat()

TEXT = """158 maisons à vendre – 74400 (Chamonix-Mont-Blanc)
Liste
Carte
Chalet à vendre 3 950 000 € 10 pièces 4 chambres 280 m² 2 800 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 25
Nouveau
3 950 000 € 14 107 €/m²
Chalet à vendre
10 pièces
·
4 chambres
·
280 m²
·
2 800 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
GM2I
À voir sur Belles Demeures
Chalet à vendre 5 975 000 € 6 pièces 5 chambres 354 m² 1 500 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 47
Nouveau
A
5 975 000 € 16 879 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
354 m²
·
1 500 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
À voir sur Belles Demeures
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Chalet à vendre 1 500 000 € 5 pièces 4 chambres 128 m² 527 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
1 / 17
Nouveau
D
1 500 000 € 11 719 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
128 m²
·
527 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
À voir sur Belles Demeures
Chalet à vendre 2 100 000 € 8 pièces 7 chambres 220 m² 660 m² de terrain Chamonix-Mont-Blanc 74400
1 / 22
Nouveau
E
2 100 000 € 9 545 €/m²
Chalet à vendre
8 pièces
·
7 chambres
·
220 m²
·
660 m² de terrain
Chamonix-Mont-Blanc (74400)
ALPES ET CHALETS
Maison à vendre 980 000 € 4 pièces 3 chambres 80 m² 75 m² de terrain Chamonix-Mont-Blanc 74400
1 / 16
Nouveau
E
980 000 € 12 250 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
80 m²
·
75 m² de terrain
Chamonix-Mont-Blanc (74400)
ExclusivitéALPES ET CHALETS
Chalet à vendre 1 800 000 € 6 pièces 4 chambres 126 m² 750 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 23
Nouveau
F
1 800 000 € 14 286 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
126 m²
·
750 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
NEW DEAL IMMOBILIER
Chalet à vendre 1 250 000 € 6 pièces 4 chambres 101 m² 605 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 21
Nouveau
E
1 250 000 € 12 376 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
101 m²
·
605 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
NEW DEAL IMMOBILIER
CLIP IMMOBILIER
Maison à vendre 1 250 000 € 4 pièces 3 chambres 101 m² 611 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
1 / 13
Nouveau
E
1 250 000 € 12 376 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
101 m²
·
611 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
CLIP IMMOBILIER
Chalet à vendre 2 990 000 € 11 pièces 10 chambres 310,1 m² 656 m² de terrain Chamonix-Mont-Blanc 74400
1 / 22
Nouveau
E
2 990 000 € 9 641 €/m²
Chalet à vendre
11 pièces
·
10 chambres
·
310,1 m²
·
656 m² de terrain
Chamonix-Mont-Blanc (74400)
PEAK CHEVALLIER IMMOBILIER
À voir sur Belles Demeures
Chalet à vendre 2 350 000 € 7 pièces 5 chambres 187,8 m² 875 m² de terrain Chamonix-Mont-Blanc 74400
1 / 17
Nouveau
B
2 350 000 € 12 511 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
187,8 m²
·
875 m² de terrain
Chamonix-Mont-Blanc (74400)
PEAK CHEVALLIER IMMOBILIER
À voir sur Belles Demeures
Chalet à vendre 298 000 € 2 pièces 1 chambre 28,6 m² Chamonix-Mont-Blanc 74400
1 / 11
Nouveau
G
298 000 € 10 420 €/m²
Chalet à vendre
2 pièces
·
1 chambre
·
28,6 m²
Chamonix-Mont-Blanc (74400)
ExclusivitéPEAK CHEVALLIER IMMOBILIER
Chalet à vendre 260 000 € 2 pièces 1 chambre 35 m² Chamonix-Mont-Blanc 74400
1 / 15
Nouveau
G
260 000 € 7 429 €/m²
Chalet à vendre
2 pièces
·
1 chambre
·
35 m²
Chamonix-Mont-Blanc (74400)
PEAK CHEVALLIER IMMOBILIER
Chalet à vendre 6 760 000 € 8 pièces 5 chambres 300 m² 1 217 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 30
Nouveau
C
6 760 000 € 22 533 €/m²
Chalet à vendre
8 pièces
·
5 chambres
·
300 m²
·
1 217 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
LA FLORIA IMMOBILIER
À voir sur Belles Demeures
Chalet à vendre 1 550 000 € 6 pièces 5 chambres 140 m² 241 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
1 / 10
Nouveau
D
1 550 000 € 11 071 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
140 m²
·
241 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
LA FLORIA IMMOBILIER
À voir sur Belles Demeures
Chalet à vendre 5 250 000 € 7 pièces 5 chambres 310 m² 2 339 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 / 25
Nouveau
D
5 250 000 € 16 935 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
310 m²
·
2 339 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
LA FLORIA IMMOBILIER
À voir sur Belles Demeures
Chalet à vendre 2 496 000 € 7 pièces 5 chambres 190 m² 830 m² de terrain Chamonix-Mont-Blanc 74400
1 / 20
Nouveau
C
2 496 000 € 13 137 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
190 m²
·
830 m² de terrain
Chamonix-Mont-Blanc (74400)
Schaefer Jérôme
Chalet à vendre 2 850 000 € 7 pièces 4 chambres 258 m² 11 631 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
1 / 19
Nouveau
D
2 850 000 € 11 047 €/m²
Chalet à vendre
7 pièces
·
4 chambres
·
258 m²
·
11 631 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
AGENCE MACONNAIS IMMOBILIER
Maison à vendre 1 890 000 € 5 pièces 3 chambres 173 m² 304 m² de terrain Chamonix-Mont-Blanc 74400
1 / 25
Nouveau
C
1 890 000 € 10 925 €/m²
Maison à vendre
5 pièces
·
3 chambres
·
173 m²
·
304 m² de terrain
Chamonix-Mont-Blanc (74400)
PHILIPPERRET IMMOBILIER
Chalet à vendre 1 500 000 € 6 pièces 4 chambres 152 m² 527 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
Nouveau
D
1 500 000 € 9 868 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
152 m²
·
527 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
NEW DEAL IMMOBILIER
Maison à vendre 1 924 000 € 5 pièces 4 chambres 160 m² 800 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
Nouveau
C
1 924 000 € 12 025 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
160 m²
·
800 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
HESTIA IMMOBILIER DE PRESTIGE
Chalet à vendre 2 390 000 € 7 pièces 6 chambres 335 m² 2 160 m² de terrain Chamonix-Mont-Blanc 74400
Nouveau
D
2 390 000 € 7 134 €/m²
Chalet à vendre
7 pièces
·
6 chambres
·
335 m²
·
2 160 m² de terrain
Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 7 000 000 € 8 pièces 5 chambres 564 m² 1 328 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
Nouveau
A
7 000 000 € 12 411 €/m²
Chalet à vendre
8 pièces
·
5 chambres
·
564 m²
·
1 328 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 2 300 000 € 6 pièces 5 chambres 239 m² 1 190 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
Nouveau
E
2 300 000 € 9 623 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
239 m²
·
1 190 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 3 250 000 € 6 pièces 5 chambres 195 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
Nouveau
D
3 250 000 € 16 667 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
195 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 3 990 000 € 6 pièces 300 m² Les Pelerins le Betty Chamonix-Mont-Blanc 74400
Nouveau
C
3 990 000 € 13 300 €/m²
Chalet à vendre
6 pièces
·
300 m²
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
CHAMONIX TRANSACTION
Chalet à vendre 3 328 000 € 9 pièces 8 chambres 154 m² 2 286 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
Nouveau
G
3 328 000 € 21 610 €/m²
Chalet à vendre
9 pièces
·
8 chambres
·
154 m²
·
2 286 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Maison à vendre 1 567 000 € 5 pièces 4 chambres 116 m² Chamonix-Mont-Blanc 74400
Nouveau
F
1 567 000 € 13 509 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
116 m²
Chamonix-Mont-Blanc (74400)
ALPES ET CHALETS
Chalet à vendre 1 490 000 € 5 pièces 4 chambres 161 m² Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
Nouveau
A
1 490 000 € 9 255 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
161 m²
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 3 990 000 € 6 pièces 4 chambres 300 m² 1 000 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
3 990 000 € 13 300 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
300 m²
·
1 000 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
CHAMONIX IMMOBILIER
Maison à vendre 1 550 000 € 8 pièces 5 chambres 168 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 550 000 € 9 226 €/m²
Maison à vendre
8 pièces
·
5 chambres
·
168 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
NEW DEAL IMMOBILIER
Chalet à vendre 2 790 000 € 10 pièces 8 chambres 310 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
2 790 000 € 9 000 €/m²
Chalet à vendre
10 pièces
·
8 chambres
·
310 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 990 000 € 4 pièces 3 chambres 120 m² 506 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
G
990 000 € 8 250 €/m²
Chalet à vendre
4 pièces
·
3 chambres
·
120 m²
·
506 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 892 500 € 5 pièces 4 chambres 92,5 m² 531 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
892 500 € 9 644 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
92,5 m²
·
531 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 3 950 000 € 8 pièces 4 chambres 300 m² 558 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
3 950 000 € 13 167 €/m²
Chalet à vendre
8 pièces
·
4 chambres
·
300 m²
·
558 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 749 000 € 5 pièces 4 chambres 152,4 m² 1 000 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
1 749 000 € 11 479 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
152,4 m²
·
1 000 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 920 000 € 5 pièces 3 chambres 159,2 m² 490 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
B
1 920 000 € 12 058 €/m²
Chalet à vendre
5 pièces
·
3 chambres
·
159,2 m²
·
490 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 924 000 € 5 pièces 4 chambres 180 m² 800 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
1 924 000 € 10 689 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
180 m²
·
800 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 500 000 € 5 pièces 4 chambres 140 m² 506 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 500 000 € 10 714 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
140 m²
·
506 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 4 380 000 € 12 pièces 10 chambres 324,4 m² 473 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
C
4 380 000 € 13 504 €/m²
Chalet à vendre
12 pièces
·
10 chambres
·
324,4 m²
·
473 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
CHX IMMOBILIER
Chalet à vendre 3 990 000 € 5 pièces 4 chambres 244,8 m² 1 000 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
3 990 000 € 16 302 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
244,8 m²
·
1 000 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 300 000 € 6 pièces 5 chambres 168 m² 317 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
2 300 000 € 13 690 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
168 m²
·
317 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Maison à vendre 980 000 € 5 pièces 4 chambres 90,5 m² 156 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
980 000 € 10 826 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
90,5 m²
·
156 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 400 000 € 6 pièces 4 chambres 208 m² 350 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 400 000 € 11 538 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
208 m²
·
350 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Maison à vendre 3 500 000 € 20 pièces 19 chambres 654 m² Les Pelerins le Betty Chamonix-Mont-Blanc 74400
A
3 500 000 € 5 352 €/m²
Maison à vendre
20 pièces
·
19 chambres
·
654 m²
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Foncia Transaction Chamonix
Chalet à vendre 1 150 000 € 4 pièces 2 chambres 99 m² 595 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
1 150 000 € 11 616 €/m²
Chalet à vendre
4 pièces
·
2 chambres
·
99 m²
·
595 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
AGENCE SCHUSS IMMOBILIER
Chalet à vendre 748 000 € 3 pièces 2 chambres 61 m² 1 140 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
748 000 € 12 262 €/m²
Chalet à vendre
3 pièces
·
2 chambres
·
61 m²
·
1 140 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CESAR ET BRUTUS
Chalet à vendre 1 995 000 € 5 pièces 4 chambres 120 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
1 995 000 € 16 625 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
120 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 2 100 000 € 8 pièces 6 chambres 220 m² 690 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
2 100 000 € 9 545 €/m²
Chalet à vendre
8 pièces
·
6 chambres
·
220 m²
·
690 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Maison à vendre 3 340 000 € 15 pièces 9 chambres 365 m² 494 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
D
3 340 000 € 9 151 €/m²
Maison à vendre
15 pièces
·
9 chambres
·
365 m²
·
494 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
CHX IMMOBILIER
Chalet à vendre 1 400 000 € 10 pièces 6 chambres 179,6 m² 935 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
G
1 400 000 € 7 795 €/m²
Chalet à vendre
10 pièces
·
6 chambres
·
179,6 m²
·
935 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 950 000 € 11 pièces 8 chambres 300 m² 178 m² de terrain Chamonix-Mont-Blanc 74400
F
2 950 000 € 9 833 €/m²
Chalet à vendre
11 pièces
·
8 chambres
·
300 m²
·
178 m² de terrain
Chamonix-Mont-Blanc (74400)
CHALETS & DEMEURES
Chalet à vendre 2 450 000 € 9 pièces 7 chambres 216 m² Les Pelerins le Betty Chamonix-Mont-Blanc 74400
D
2 450 000 € 11 343 €/m²
Chalet à vendre
9 pièces
·
7 chambres
·
216 m²
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 600 000 € 7 pièces 6 chambres 188 m² 962 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
B
2 600 000 € 13 830 €/m²
Chalet à vendre
7 pièces
·
6 chambres
·
188 m²
·
962 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
ISABELLE IMMOBILIER
Maison à vendre 1 920 000 € 4 pièces 3 chambres 134 m² 77 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
D
1 920 000 € 14 328 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
134 m²
·
77 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
Chalet à vendre 1 920 000 € 1 pièce 4 chambres 132,4 m² 497 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
B
1 920 000 € 14 502 €/m²
Chalet à vendre
1 pièce
·
4 chambres
·
132,4 m²
·
497 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 1 390 000 € 5 pièces 4 chambres 177 m² 1 000 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
1 390 000 € 7 853 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
177 m²
·
1 000 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CHAMONIX IMMOBILIER
Maison à vendre 2 500 000 € 6 pièces 5 chambres 190 m² 830 m² de terrain Chamonix-Mont-Blanc 74400
C
2 500 000 € 13 158 €/m²
Maison à vendre
6 pièces
·
5 chambres
·
190 m²
·
830 m² de terrain
Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Maison à vendre 1 050 000 € 5 pièces 4 chambres 704 m² 1 628 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
E
1 050 000 € 1 491 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
704 m²
·
1 628 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
efficity Edouard Fournier
Maison à vendre 892 500 € 6 pièces 4 chambres 93 m² 538 m² de terrain Chamonix-Mont-Blanc 74400
E
892 500 € 9 597 €/m²
Maison à vendre
6 pièces
·
4 chambres
·
93 m²
·
538 m² de terrain
Chamonix-Mont-Blanc (74400)
ALPES ET CHALETS
Chalet à vendre 4 600 000 € 10 pièces 5 chambres 352 m² 2 528 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
4 600 000 € 13 068 €/m²
Chalet à vendre
10 pièces
·
5 chambres
·
352 m²
·
2 528 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 150 000 € 5 pièces 4 chambres 109 m² Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
D
2 150 000 € 19 725 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
109 m²
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 980 000 € 9 pièces 9 chambres 315 m² 1 713 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
2 980 000 € 9 460 €/m²
Chalet à vendre
9 pièces
·
9 chambres
·
315 m²
·
1 713 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Maison à vendre 1 924 000 € 6 pièces 4 chambres 180 m² 800 m² de terrain Chamonix-Mont-Blanc 74400
C
1 924 000 € 10 689 €/m²
Maison à vendre
6 pièces
·
4 chambres
·
180 m²
·
800 m² de terrain
Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Maison à vendre 1 612 000 € 5 pièces 4 chambres 131,4 m² 600 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
F
1 612 000 € 12 265 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
131,4 m²
·
600 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Chalet à vendre 4 600 000 € 8 pièces 5 chambres 262 m² 769 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
4 600 000 € 17 557 €/m²
Chalet à vendre
8 pièces
·
5 chambres
·
262 m²
·
769 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHX IMMOBILIER
Chalet à vendre 2 350 000 € 6 pièces 5 chambres 187 m² 962 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
2 350 000 € 12 567 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
187 m²
·
962 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CIMALPES Chamonix
Chalet à vendre 3 950 000 € 6 pièces 4 chambres 217 m² 1 594 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
3 950 000 € 18 203 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
217 m²
·
1 594 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 150 000 € 6 pièces 5 chambres 313 m² 465 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
2 150 000 € 6 869 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
313 m²
·
465 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 100 000 € 7 pièces 6 chambres 236 m² 690 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 100 000 € 8 898 €/m²
Chalet à vendre
7 pièces
·
6 chambres
·
236 m²
·
690 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 995 000 € 6 pièces 4 chambres 179 m² 989 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 995 000 € 16 732 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
179 m²
·
989 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHAMONIX IMMOBILIER
Maison à vendre 1 600 000 € 1 pièce 120 m² 3 500 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
1 600 000 € 13 333 €/m²
Maison à vendre
1 pièce
·
120 m²
·
3 500 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Maison à vendre 1 604 250 € 5 pièces 3 chambres 143 m² 599 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
F
1 604 250 € 11 219 €/m²
Maison à vendre
5 pièces
·
3 chambres
·
143 m²
·
599 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
iad France Patrice LE GUELLEC
Maison à vendre 2 950 000 € 9 pièces 8 chambres 347 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 950 000 € 8 501 €/m²
Maison à vendre
9 pièces
·
8 chambres
·
347 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Maison à vendre 5 250 000 € 9 pièces 5 chambres 313 m² 2 339 m² de terrain Chamonix-Mont-Blanc 74400
D
5 250 000 € 16 773 €/m²
Maison à vendre
9 pièces
·
5 chambres
·
313 m²
·
2 339 m² de terrain
Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Maison à vendre 1 749 000 € 4 pièces 4 chambres 147,8 m² 1 000 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 749 000 € 11 833 €/m²
Maison à vendre
4 pièces
·
4 chambres
·
147,8 m²
·
1 000 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 2 000 000 € 5 pièces 4 chambres 188,5 m² 273 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
E
2 000 000 € 10 612 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
188,5 m²
·
273 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 3 250 000 € 7 pièces 5 chambres 195 m² 1 500 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
3 250 000 € 16 667 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
195 m²
·
1 500 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 995 000 € 6 pièces 5 chambres 178,8 m² 989 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 995 000 € 16 752 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
178,8 m²
·
989 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 339 000 € 5 pièces 3 chambres 102,1 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
2 339 000 € 22 900 €/m²
Chalet à vendre
5 pièces
·
3 chambres
·
102,1 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
ALPES SIGNATURE
Chalet à vendre 1 995 000 € 5 pièces 4 chambres 111,9 m² 708 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
1 995 000 € 17 835 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
111,9 m²
·
708 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 5 100 000 € 9 pièces 6 chambres 226 m² 3 787 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
5 100 000 € 22 566 €/m²
Chalet à vendre
9 pièces
·
6 chambres
·
226 m²
·
3 787 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 950 000 € 11 pièces 8 chambres 300 m² 178 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
F
2 950 000 € 9 833 €/m²
Chalet à vendre
11 pièces
·
8 chambres
·
300 m²
·
178 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHALETS & DEMEURES
Chalet à vendre 1 290 000 € 7 pièces 6 chambres 140 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
F
1 290 000 € 9 214 €/m²
Chalet à vendre
7 pièces
·
6 chambres
·
140 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
AGENCE SCHUSS IMMOBILIER
Chalet à vendre 1 950 000 € 7 pièces 5 chambres 184 m² 1 430 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
C
1 950 000 € 10 598 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
184 m²
·
1 430 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
efficity Benoît Wartel
Chalet à vendre 990 000 € 5 pièces 130 m² 546 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
G
990 000 € 7 615 €/m²
Chalet à vendre
5 pièces
·
130 m²
·
546 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 500 000 € 5 pièces 140 m² 560 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 500 000 € 10 714 €/m²
Chalet à vendre
5 pièces
·
140 m²
·
560 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 2 680 000 € 6 pièces 5 chambres 167 m² 500 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
2 680 000 € 16 048 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
167 m²
·
500 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
PRAZ & ASSOCIES
Chalet à vendre 2 150 000 € 5 pièces 4 chambres 132 m² 416 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
D
2 150 000 € 16 288 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
132 m²
·
416 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Maison à vendre 790 000 € 3 pièces 2 chambres 74,7 m² 175 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
E
790 000 € 10 581 €/m²
Maison à vendre
3 pièces
·
2 chambres
·
74,7 m²
·
175 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
efficity Martin Beaujouan
Maison à vendre 1 950 000 € 5 chambres 168 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
1 950 000 € 11 607 €/m²
Maison à vendre
5 chambres
·
168 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 1 300 000 € 8 pièces 7 chambres 196 m² 1 218 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 300 000 € 6 633 €/m²
Chalet à vendre
8 pièces
·
7 chambres
·
196 m²
·
1 218 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
ALPIHOME
Chalet à vendre 1 390 000 € 5 pièces 4 chambres 177 m² 1 130 m² de terrain Chamonix-Mont-Blanc 74400
B
1 390 000 € 7 853 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
177 m²
·
1 130 m² de terrain
Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Maison à vendre 1 800 000 € 5 pièces 4 chambres 140 m² 750 m² de terrain Chamonix-Mont-Blanc 74400
F
1 800 000 € 12 857 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
140 m²
·
750 m² de terrain
Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Maison à vendre 2 600 000 € 8 pièces 6 chambres 255 m² 2 800 m² de terrain Chamonix-Mont-Blanc 74400
D
2 600 000 € 10 196 €/m²
Maison à vendre
8 pièces
·
6 chambres
·
255 m²
·
2 800 m² de terrain
Chamonix-Mont-Blanc (74400)
CENTURY 21 Mont-Blanc Invest
Maison à vendre 2 100 000 € 8 pièces 7 chambres 210 m² 960 m² de terrain Chamonix-Mont-Blanc 74400
E
2 100 000 € 10 000 €/m²
Maison à vendre
8 pièces
·
7 chambres
·
210 m²
·
960 m² de terrain
Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Maison à vendre 825 000 € 3 pièces 2 chambres 85,8 m² 175 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
E
825 000 € 9 613 €/m²
Maison à vendre
3 pièces
·
2 chambres
·
85,8 m²
·
175 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
efficity Martin Beaujouan
Chalet à vendre 2 750 000 € 7 pièces 160 m² 830 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
2 750 000 € 17 188 €/m²
Chalet à vendre
7 pièces
·
160 m²
·
830 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
FGP Swiss & Alps I Forbes Global Properties
Maison à vendre 892 500 € 5 pièces 4 chambres 81,5 m² Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
E
892 500 € 10 954 €/m²
Maison à vendre
5 pièces
·
4 chambres
·
81,5 m²
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Chalet à vendre 892 500 € 5 pièces 4 chambres 92,5 m² 531 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
E
892 500 € 9 644 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
92,5 m²
·
531 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 9 990 000 € 13 pièces 11 chambres 643 m² 2 091 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
9 990 000 € 15 537 €/m²
Chalet à vendre
13 pièces
·
11 chambres
·
643 m²
·
2 091 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 8 950 000 € 8 pièces 5 chambres 525 m² 1 350 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
8 950 000 € 17 048 €/m²
Chalet à vendre
8 pièces
·
5 chambres
·
525 m²
·
1 350 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 10 500 000 € 14 pièces 8 chambres 594 m² 3 025 m² de terrain Chamonix-Mont-Blanc 74400
D
10 500 000 € 17 677 €/m²
Chalet à vendre
14 pièces
·
8 chambres
·
594 m²
·
3 025 m² de terrain
Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Chalet à vendre 5 100 000 € 9 pièces 6 chambres 295 m² 3 787 m² de terrain Chamonix-Mont-Blanc 74400
C
5 100 000 € 17 288 €/m²
Chalet à vendre
9 pièces
·
6 chambres
·
295 m²
·
3 787 m² de terrain
Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Chalet à vendre 4 925 000 € 12 pièces 5 chambres 387 m² 1 270 m² de terrain Chamonix-Mont-Blanc 74400
B
4 925 000 € 12 726 €/m²
Chalet à vendre
12 pièces
·
5 chambres
·
387 m²
·
1 270 m² de terrain
Chamonix-Mont-Blanc (74400)
CHAMONIX SOTHEBY S INTERNATIONAL REALTY
Chalet à vendre 1 550 000 € 7 pièces 5 chambres 168 m² Chamonix-Mont-Blanc 74400
1 550 000 € 9 226 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
168 m²
Chamonix-Mont-Blanc (74400)
PEAK CHEVALLIER IMMOBILIER
Chalet à vendre 2 150 000 € 6 pièces 1 chambre 133 m² 500 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
2 150 000 € 16 165 €/m²
Chalet à vendre
6 pièces
·
1 chambre
·
133 m²
·
500 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
PRAZ & ASSOCIES
Maison à vendre 1 395 595 € 4 pièces 3 chambres 150 m² 800 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
D
1 395 595 € 9 304 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
150 m²
·
800 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Foncia Transaction Chamonix
Chalet à vendre 1 300 000 € 9 pièces 7 chambres 192,6 m² Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 300 000 € 6 750 €/m²
Chalet à vendre
9 pièces
·
7 chambres
·
192,6 m²
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
ANTOINE IMMOBILIER SARL
Maison à vendre 12 390 000 € 12 pièces 11 chambres 556 m² Chamonix-Mont-Blanc 74400
A
12 390 000 € 22 284 €/m²
Maison à vendre
12 pièces
·
11 chambres
·
556 m²
Chamonix-Mont-Blanc (74400)
Foncia Transaction Chamonix
Chalet à vendre 2 500 000 € 6 pièces 5 chambres 198 m² Les Pelerins le Betty Chamonix-Mont-Blanc 74400
C
2 500 000 € 12 626 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
198 m²
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Foncia Transaction Chamonix
Maison à vendre 1 390 000 € 6 pièces 4 chambres 177 m² 1 100 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
C
1 390 000 € 7 853 €/m²
Maison à vendre
6 pièces
·
4 chambres
·
177 m²
·
1 100 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CHAPELON THIERRY
Chalet à vendre 890 000 € 3 pièces 2 chambres 60 m² 300 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
890 000 € 14 833 €/m²
Chalet à vendre
3 pièces
·
2 chambres
·
60 m²
·
300 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Maison à vendre 2 300 000 € 6 pièces 6 chambres 249,5 m² 1 062 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
2 300 000 € 9 220 €/m²
Maison à vendre
6 pièces
·
6 chambres
·
249,5 m²
·
1 062 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
Mont-Blanc Immobilier II Chamonix
Chalet à vendre 1 369 000 € 14 pièces 8 chambres 194,3 m² 254 m² de terrain Chamonix-Mont-Blanc 74400
G
1 369 000 € 7 048 €/m²
Chalet à vendre
14 pièces
·
8 chambres
·
194,3 m²
·
254 m² de terrain
Chamonix-Mont-Blanc (74400)
AGENCE SCHUSS IMMOBILIER
Chalet à vendre 1 400 000 € 16 pièces 12 chambres 263,7 m² Chamonix-Mont-Blanc 74400
G
1 400 000 € 5 309 €/m²
Chalet à vendre
16 pièces
·
12 chambres
·
263,7 m²
Chamonix-Mont-Blanc (74400)
AGENCE SCHUSS IMMOBILIER
Maison à vendre 1 785 000 € 17 pièces 275 m² Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
E
1 785 000 € 6 491 €/m²
Maison à vendre
17 pièces
·
275 m²
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
CHAMONIX TRANSACTION
Chalet à vendre 1 200 000 € 6 pièces 5 chambres 160 m² 600 m² de terrain Chamonix-Mont-Blanc 74400
D
1 200 000 € 7 500 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
160 m²
·
600 m² de terrain
Chamonix-Mont-Blanc (74400)
Alpine Property
Chalet à vendre 1 390 000 € 5 pièces 4 chambres 176,9 m² 1 000 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
B
1 390 000 € 7 860 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
176,9 m²
·
1 000 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 748 000 € 3 pièces 2 chambres 44 m² 1 140 m² de terrain Chamonix-Mont-Blanc 74400
748 000 € 17 000 €/m²
Chalet à vendre
3 pièces
·
2 chambres
·
44 m²
·
1 140 m² de terrain
Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 5 250 000 € 6 pièces 5 chambres 313 m² 2 339 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
5 250 000 € 16 773 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
313 m²
·
2 339 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 1 130 000 € 5 pièces 3 chambres 88,6 m² 300 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 130 000 € 12 760 €/m²
Chalet à vendre
5 pièces
·
3 chambres
·
88,6 m²
·
300 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 1 920 000 € 5 pièces 3 chambres 159,2 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
B
1 920 000 € 12 058 €/m²
Chalet à vendre
5 pièces
·
3 chambres
·
159,2 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 2 790 000 € 10 pièces 8 chambres 310 m² Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
F
2 790 000 € 9 000 €/m²
Chalet à vendre
10 pièces
·
8 chambres
·
310 m²
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 1 924 000 € 5 pièces 180 m² 800 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
C
1 924 000 € 10 689 €/m²
Chalet à vendre
5 pièces
·
180 m²
·
800 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
JULIETTE CO IMMOBILIER
Chalet à vendre 9 990 000 € 15 pièces 623 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
9 990 000 € 16 035 €/m²
Chalet à vendre
15 pièces
·
623 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHAMONIX IMMOBILIER
Chalet à vendre 2 950 000 € 9 pièces 8 chambres 299 m² 178 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
2 950 000 € 9 866 €/m²
Chalet à vendre
9 pièces
·
8 chambres
·
299 m²
·
178 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 5 975 000 € 6 pièces 5 chambres 354 m² 1 500 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
5 975 000 € 16 879 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
354 m²
·
1 500 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Douglas Elliman France Chamonix
Chalet à vendre 2 300 000 € 5 pièces 149 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
2 300 000 € 15 436 €/m²
Chalet à vendre
5 pièces
·
149 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
AGENCE MONTAGNE
Chalet à vendre 1 550 000 € 6 pièces 5 chambres 174 m² 241 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
D
1 550 000 € 8 908 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
174 m²
·
241 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
Alpine Property
Maison à vendre 4 600 000 € 7 pièces 5 chambres 377 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
4 600 000 € 12 202 €/m²
Maison à vendre
7 pièces
·
5 chambres
·
377 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Maison à vendre 2 950 000 € 9 pièces 8 chambres 280 m² 178 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
2 950 000 € 10 536 €/m²
Maison à vendre
9 pièces
·
8 chambres
·
280 m²
·
178 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Chalet à vendre 1 924 000 € 1 pièce 4 chambres 180 m² 800 m² de terrain Les Pelerins le Betty Chamonix-Mont-Blanc 74400
C
1 924 000 € 10 689 €/m²
Chalet à vendre
1 pièce
·
4 chambres
·
180 m²
·
800 m² de terrain
Les Pelerins le Betty, Chamonix-Mont-Blanc (74400)
CHAMONIX IMMOBILIER
Chalet à vendre 1 950 000 € 7 pièces 5 chambres 196 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
1 950 000 € 9 949 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
196 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
SAVILLS UK LIMITED
Chalet à vendre 1 924 000 € 6 pièces 180 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
1 924 000 € 10 689 €/m²
Chalet à vendre
6 pièces
·
180 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Maison à vendre 2 100 000 € 8 pièces 6 chambres 157 m² 690 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
D
2 100 000 € 13 376 €/m²
Maison à vendre
8 pièces
·
6 chambres
·
157 m²
·
690 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Maison à vendre 820 000 € 4 pièces 3 chambres 92,2 m² 565 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
820 000 € 8 893 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
92,2 m²
·
565 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Maison à vendre 895 000 € 4 pièces 3 chambres 108,5 m² 667 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
895 000 € 8 253 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
108,5 m²
·
667 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
Coldwell Banker La Clé des Cimes
Maison à vendre 3 900 000 € 8 pièces 5 chambres 340 m² 1 700 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
3 900 000 € 11 471 €/m²
Maison à vendre
8 pièces
·
5 chambres
·
340 m²
·
1 700 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
ANTOINE IMMOBILIER SARL
Maison à vendre 1 995 000 € 5 pièces 170 m² La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
G
1 995 000 € 11 735 €/m²
Maison à vendre
5 pièces
·
170 m²
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
CHAMONIX TRANSACTION
Maison à vendre 359 000 € 3 pièces 3 chambres 121 m² 450 m² de terrain Chamonix-Mont-Blanc 74400
359 000 € 2 967 €/m²
Maison à vendre
3 pièces
·
3 chambres
·
121 m²
·
450 m² de terrain
Chamonix-Mont-Blanc (74400)
NOMADU
Chalet à vendre 1 950 000 € 6 pièces 5 chambres 186 m² 1 430 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 950 000 € 10 484 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
186 m²
·
1 430 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 300 000 € 6 pièces 5 chambres 239 m² 1 190 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
E
2 300 000 € 9 623 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
239 m²
·
1 190 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
Alpine Property
Chalet à vendre 7 000 000 € 7 pièces 5 chambres 338 m² 1 328 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
A
7 000 000 € 20 710 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
338 m²
·
1 328 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Maison à vendre 2 950 000 € 9 pièces 8 chambres 299 m² 178 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
E
2 950 000 € 9 866 €/m²
Maison à vendre
9 pièces
·
8 chambres
·
299 m²
·
178 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 4 600 000 € 7 pièces 5 chambres 352,1 m² 2 528 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
A
4 600 000 € 13 064 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
352,1 m²
·
2 528 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 250 000 € 8 pièces 265 m² 508 m² de terrain Chamonix Sud-Bois du Bouchet Chamonix-Mont-Blanc 74400
D
2 250 000 € 8 491 €/m²
Chalet à vendre
8 pièces
·
265 m²
·
508 m² de terrain
Chamonix Sud-Bois du Bouchet, Chamonix-Mont-Blanc (74400)
ALPS PROPERTY
Chalet à vendre 6 760 000 € 8 pièces 5 chambres 311,8 m² 1 217 m² de terrain La Tour-Argentière-Les Praz Chamonix-Mont-Blanc 74400
C
6 760 000 € 21 678 €/m²
Chalet à vendre
8 pièces
·
5 chambres
·
311,8 m²
·
1 217 m² de terrain
La Tour-Argentière-Les Praz, Chamonix-Mont-Blanc (74400)
BARNES MONT-BLANC Chamonix
Chalet à vendre 1 300 000 € 9 pièces 7 chambres 196 m² 1 218 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 300 000 € 6 633 €/m²
Chalet à vendre
9 pièces
·
7 chambres
·
196 m²
·
1 218 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
Alpine Property
Chalet à vendre 1 950 000 € 8 pièces 4 chambres 148,3 m² 1 430 m² de terrain Les Bossons les Moussoux Chamonix-Mont-Blanc 74400
D
1 950 000 € 13 145 €/m²
Chalet à vendre
8 pièces
·
4 chambres
·
148,3 m²
·
1 430 m² de terrain
Les Bossons les Moussoux, Chamonix-Mont-Blanc (74400)
ANTOINE IMMOBILIER SARL
Maison à vendre 1 070 000 € 4 pièces 3 chambres 168 m² 1 000 m² de terrain Les Houches 74310
D
1 070 000 € 6 369 €/m²
Maison à vendre
4 pièces
·
3 chambres
·
168 m²
·
1 000 m² de terrain
Les Houches (74310)
PEAK CHEVALLIER IMMOBILIER
Chalet à vendre 995 000 € 4 pièces 3 chambres 100,3 m² 706 m² de terrain Les Houches 74310
E
995 000 € 9 921 €/m²
Chalet à vendre
4 pièces
·
3 chambres
·
100,3 m²
·
706 m² de terrain
Les Houches (74310)
BARNES MONT-BLANC Chamonix
Maison à vendre 2 400 000 € 10 pièces 4 chambres 330 m² 2 963 m² de terrain Les Houches 74310
G
2 400 000 € 7 273 €/m²
Maison à vendre
10 pièces
·
4 chambres
·
330 m²
·
2 963 m² de terrain
Les Houches (74310)
CESAR ET BRUTUS
Chalet à vendre 3 450 000 € 8 pièces 420 m² 1 014 m² de terrain Les Houches 74310
B
3 450 000 € 8 214 €/m²
Chalet à vendre
8 pièces
·
420 m²
·
1 014 m² de terrain
Les Houches (74310)
FGP Swiss & Alps I Forbes Global Properties
Maison à vendre 2 600 500 € 9 pièces 5 chambres 266 m² 461 m² de terrain Les Houches 74310
2 600 500 € 9 776 €/m²
Maison à vendre
9 pièces
·
5 chambres
·
266 m²
·
461 m² de terrain
Les Houches (74310)
Gisela ROGER
Chalet à vendre 4 890 000 € 10 pièces 5 chambres 352 m² 1 577 m² de terrain Les Houches 74310
C
4 890 000 € 13 892 €/m²
Chalet à vendre
10 pièces
·
5 chambres
·
352 m²
·
1 577 m² de terrain
Les Houches (74310)
CIMALPES Chamonix
Chalet à vendre 1 290 000 € 6 pièces 5 chambres 150 m² 941 m² de terrain Les Houches 74310
D
1 290 000 € 8 600 €/m²
Chalet à vendre
6 pièces
·
5 chambres
·
150 m²
·
941 m² de terrain
Les Houches (74310)
LA FLORIA IMMOBILIER
Chalet à vendre 3 450 000 € 13 pièces 6 chambres 380 m² 1 014 m² de terrain Les Houches 74310
B
3 450 000 € 9 079 €/m²
Chalet à vendre
13 pièces
·
6 chambres
·
380 m²
·
1 014 m² de terrain
Les Houches (74310)
BARNES MONT-BLANC Chamonix
Maison à vendre 1 800 000 € 8 pièces 5 chambres 250 m² 686 m² de terrain Les Houches 74310
C
1 800 000 € 7 200 €/m²
Maison à vendre
8 pièces
·
5 chambres
·
250 m²
·
686 m² de terrain
Les Houches (74310)
Coldwell Banker La Clé des Cimes
Chalet à vendre 1 590 000 € 6 pièces 4 chambres 172 m² Les Houches 74310
C
1 590 000 € 9 244 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
172 m²
Les Houches (74310)
ALPS PROPERTY
Chalet à vendre 1 560 000 € 6 pièces 4 chambres 128 m² 780 m² de terrain Les Houches 74310
C
1 560 000 € 12 188 €/m²
Chalet à vendre
6 pièces
·
4 chambres
·
128 m²
·
780 m² de terrain
Les Houches (74310)
Douglas Elliman France Chamonix
Maison à vendre 2 400 000 € 10 pièces 128 m² 2 922 m² de terrain Les Houches 74310
G
2 400 000 € 18 750 €/m²
Maison à vendre
10 pièces
·
128 m²
·
2 922 m² de terrain
Les Houches (74310)
BARNES MONT-BLANC Chamonix
Chalet à vendre 3 450 000 € 12 pièces 5 chambres 380 m² Les Houches 74310
B
3 450 000 € 9 079 €/m²
Chalet à vendre
12 pièces
·
5 chambres
·
380 m²
Les Houches (74310)
Coldwell Banker La Clé des Cimes
Maison à vendre 4 800 000 € 10 pièces 6 chambres 476 m² Les Houches 74310
B
4 800 000 € 10 084 €/m²
Maison à vendre
10 pièces
·
6 chambres
·
476 m²
Les Houches (74310)
Coldwell Banker La Clé des Cimes
Chalet à vendre 1 560 000 € 7 pièces 4 chambres 127,5 m² Les Houches 74310
C
1 560 000 € 12 235 €/m²
Chalet à vendre
7 pièces
·
4 chambres
·
127,5 m²
Les Houches (74310)
AGENCE MONTAGNE
Chalet à vendre 1 490 000 € 5 pièces 4 chambres 172,6 m² 933 m² de terrain Les Houches 74310
C
1 490 000 € 8 631 €/m²
Chalet à vendre
5 pièces
·
4 chambres
·
172,6 m²
·
933 m² de terrain
Les Houches (74310)
BARNES MONT-BLANC Chamonix
Chalet à vendre 2 300 000 € 7 pièces 5 chambres 274,3 m² Les Houches 74310
E
2 300 000 € 8 386 €/m²
Chalet à vendre
7 pièces
·
5 chambres
·
274,3 m²
Les Houches (74310)
ANTOINE IMMOBILIER SARL
Chalet à vendre 850 000 € 4 pièces 2 chambres 121,9 m² Les Houches 74310
F
850 000 € 6 975 €/m²
Chalet à vendre
4 pièces
·
2 chambres
·
121,9 m²
Les Houches (74310)
Foncia Transaction Les Houches
Maison à vendre 1 490 000 € 6 pièces 4 chambres 151,7 m² 933 m² de terrain Les Houches 74310
C
1 490 000 € 9 819 €/m²
Maison à vendre
6 pièces
·
4 chambres
·
151,7 m²
·
933 m² de terrain
Les Houches (74310)
Engel & Völkers Chamonix-Mont-Blanc
Maison à vendre 950 000 € 7 pièces 4 chambres 144 m² Les Houches 74310
C
950 000 € 6 597 €/m²
Maison à vendre
7 pièces
·
4 chambres
·
144 m²
Les Houches (74310)
Coldwell Banker La Clé des Cimes
Maison à vendre 1 800 000 € 6 pièces 5 chambres 250 m² 686 m² de terrain Les Houches 74310
D
1 800 000 € 7 200 €/m²
Maison à vendre
6 pièces
·
5 chambres
·
250 m²
·
686 m² de terrain
Les Houches (74310)
NEW DEAL IMMOBILIER"""

# ── Parser ────────────────────────────────────────────────────────────────────
SUMMARY_RE = re.compile(
    r'^(Chalet|Maison|Villa|Propriété)\s+à\s+vendre(?:\s*-\s*[^€\n\d]*?)?\s+'
    r'([\d\s\xa0]{3,15})\s*€\s+'
    r'(\d+)\s*pièces?\s*'
    r'(?:(\d+)\s*chambres?\s+)?'
    r'([\d,\.]+)\s*m²'
    r'(?:\s+([\d\s]+)\s*m²\s+de\s+terrain)?'
    r'\s+(.*?)\s*(Chamonix-Mont-Blanc|Les Houches|74400|74310)',
    re.IGNORECASE | re.MULTILINE
)

QUARTIER_MAP = {
    "la tour-argentière-les praz": "La Tour - Argentière - Les Praz",
    "argentière": "Argentière",
    "les pelerins le betty": "Les Pélerins - Le Betty",
    "chamonix sud-bois du bouchet": "Chamonix Sud - Bois du Bouchet",
    "les bossons les moussoux": "Les Bossons - Les Moussoux",
    "les houches": "Les Houches",
}

def norm_quartier(raw):
    r = raw.lower().strip()
    for k, v in QUARTIER_MAP.items():
        if k in r: return v
    return raw.strip()

def parse_prix(s):
    s = re.sub(r'[\s\xa0]', '', s)
    try: return int(s)
    except: return None

parsed = []
seen   = set()  # dedup (prix, surface, type)

for m in SUMMARY_RE.finditer(TEXT):
    type_bien  = m.group(1).lower()
    prix_raw   = m.group(2)
    pieces     = int(m.group(3)) if m.group(3) else 0
    chambres   = int(m.group(4)) if m.group(4) else 0
    surf_raw   = m.group(5).replace(',', '.')
    terrain_raw= m.group(6)
    quartier   = m.group(7)
    commune_raw= m.group(8)

    prix = parse_prix(prix_raw)
    if not prix or prix < 100_000: continue

    try: surface = float(surf_raw)
    except: continue
    if surface < 10: continue
    if surface > 400: continue   # mega-chalets hors distribution AVM (DVF max 390m²)

    terrain = None
    if terrain_raw:
        try: terrain = float(re.sub(r'\s', '', terrain_raw))
        except: pass

    commune = "LES HOUCHES" if "houches" in commune_raw.lower() else "CHAMONIX MONT BLANC"
    cp      = "74310" if commune == "LES HOUCHES" else "74400"
    quartier_norm = norm_quartier(quartier)

    key = (prix, surface, type_bien, commune)
    if key in seen: continue
    seen.add(key)

    prix_m2 = round(prix / surface)
    parsed.append({
        "type_local":   type_bien,
        "commune":      commune,
        "code_postal":  cp,
        "adresse_raw":  quartier_norm,
        "surface":      surface,
        "surf_terrain": terrain,
        "pieces":       pieces,
        "chambres":     chambres,
        "prix":         prix,
        "prix_m2":      prix_m2,
    })

print(f"Listings parsés (après dedup) : {len(parsed)}")

# ── Insertion DB ──────────────────────────────────────────────────────────────
con = sqlite3.connect(DB)
inserted = 0
for l in parsed:
    try:
        con.execute("""
            INSERT OR IGNORE INTO maisons
            (source, commune, code_postal, adresse_raw, type_local,
             surface, surf_terrain, pieces, chambres,
             prix, prix_initial, historique_prix,
             date_import, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            "seloger", l["commune"], l["code_postal"], l["adresse_raw"], l["type_local"],
            l["surface"], l["surf_terrain"], l["pieces"], l["chambres"],
            l["prix"], l["prix"], json.dumps([{"date": TODAY, "prix": l["prix"]}]),
            TODAY, TODAY, TODAY
        ))
        inserted += con.execute("SELECT changes()").fetchone()[0]
    except Exception as e:
        print(f"  Err: {e} — {l}")

con.commit()

# ── Stats ─────────────────────────────────────────────────────────────────────
total = con.execute("SELECT COUNT(*) FROM maisons").fetchone()[0]
print(f"Insérés : {inserted}  |  Total DB : {total}")
print()

rows = con.execute("""
    SELECT commune, type_local,
           COUNT(*) n,
           MIN(prix) prix_min, MAX(prix) prix_max,
           ROUND(AVG(prix)) prix_moy,
           ROUND(AVG(prix/surface)) pm2_moy
    FROM maisons
    GROUP BY commune, type_local
    ORDER BY commune, n DESC
""").fetchall()

print(f"{'Commune':<28} {'Type':<10} {'N':>4}  {'Min':>12}  {'Max':>12}  {'Moy':>12}  {'€/m²':>8}")
print("─" * 85)
for r in rows:
    def fm(p): return f"{p/1e6:.2f}M€" if p else "-"
    print(f"{r[0]:<28} {r[1]:<10} {r[2]:>4}  {fm(r[3]):>12}  {fm(r[4]):>12}  {fm(r[5]):>12}  {int(r[6] or 0):>8}")

con.close()
print(f"\nDB : {DB}")
print("Colonnes section/plu_typezone/notes → à remplir manuellement.")
