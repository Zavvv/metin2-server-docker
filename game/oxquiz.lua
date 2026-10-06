-- The OX quiz's questions (OXEvent.cpp, oxevent_manager.quest). The image
-- copies this file over the package's locale/poland/oxquiz.lua, which was the
-- German server's ("pytania sa chyba po niemiecku", Malina, 29 September); no
-- Polish set came with the package or with r40250's share, so this one is
-- ours.
--
-- add_ox_quiz(level, question, answer, english): the quest asks level 1; the
-- answer is true for O and false for X; the fourth argument is the question's
-- English twin, which a player whose client reads English is asked instead
-- (playerbotify apply_ox_event). Polish without diacritics, and no double
-- quote or backslash in a question.
--
-- The Metin2 questions are this world's: the monsters' levels are
-- world.mob_proto's, the kingdoms and their villages the engine's own quests'
-- (new_quest_lv52, new_quest_lv7), the Demon Tower's forty
-- deviltower_zone.quest's and the horse's twenty-five pony_buy.quest's, the
-- NPCs the ones standing in this world. A question whose answer the world
-- changes belongs out of this file.

-- The kingdoms and their villages.
add_ox_quiz(1, "Czy Shinsoo to krolestwo czerwone?", true, "Is Shinsoo the red kingdom?")
add_ox_quiz(1, "Czy Chunjo to krolestwo niebieskie?", false, "Is Chunjo the blue kingdom?")
add_ox_quiz(1, "Czy Jinno to krolestwo niebieskie?", true, "Is Jinno the blue kingdom?")
add_ox_quiz(1, "Czy Chunjo to krolestwo zolte?", true, "Is Chunjo the yellow kingdom?")
add_ox_quiz(1, "Czy Joan to pierwsza wioska krolestwa Chunjo?", true, "Is Joan the first village of the Chunjo kingdom?")
add_ox_quiz(1, "Czy Yongan to pierwsza wioska krolestwa Jinno?", false, "Is Yongan the first village of the Jinno kingdom?")
add_ox_quiz(1, "Czy Pyongmoo to pierwsza wioska krolestwa Shinsoo?", false, "Is Pyongmoo the first village of the Shinsoo kingdom?")
add_ox_quiz(1, "Czy Bokjung to druga wioska krolestwa Chunjo?", true, "Is Bokjung the second village of the Chunjo kingdom?")
add_ox_quiz(1, "Czy Bakra to druga wioska krolestwa Shinsoo?", false, "Is Bakra the second village of the Shinsoo kingdom?")
add_ox_quiz(1, "Czy Jayang to druga wioska krolestwa Shinsoo?", true, "Is Jayang the second village of the Shinsoo kingdom?")

-- The classes and their weapons.
add_ox_quiz(1, "Czy Szaman moze walczyc wachlarzem?", true, "Can a Shaman fight with a fan?")
add_ox_quiz(1, "Czy Szaman moze walczyc dzwonem?", true, "Can a Shaman fight with a bell?")
add_ox_quiz(1, "Czy Szaman moze walczyc mieczem dwurecznym?", false, "Can a Shaman fight with a two-handed sword?")
add_ox_quiz(1, "Czy Sura moze strzelac z luku?", false, "Can a Sura shoot a bow?")
add_ox_quiz(1, "Czy Ninja moze walczyc lukiem?", true, "Can a Ninja fight with a bow?")
add_ox_quiz(1, "Czy Ninja moze walczyc sztyletami?", true, "Can a Ninja fight with daggers?")
add_ox_quiz(1, "Czy Wojownik moze walczyc bronia dwureczna?", true, "Can a Warrior fight with a two-handed weapon?")
add_ox_quiz(1, "Czy Wojownik moze walczyc wachlarzem?", false, "Can a Warrior fight with a fan?")
add_ox_quiz(1, "Czy Ninja potrafi stac sie niewidzialny?", true, "Can a Ninja turn invisible?")
add_ox_quiz(1, "Czy Sura wlada czarna magia?", true, "Does a Sura wield black magic?")
add_ox_quiz(1, "Czy sciezke umiejetnosci wybiera sie od 5 poziomu?", true, "Do you choose your skill path from level 5?")

-- The people of the villages.
add_ox_quiz(1, "Czy Konkurs OX prowadzi Uriel?", true, "Is the OX Quiz run by Uriel?")
add_ox_quiz(1, "Czy Uriel stoi w drugich wioskach krolestw?", false, "Does Uriel stand in the second villages of the kingdoms?")
add_ox_quiz(1, "Czy Kowal ulepsza bron i zbroje?", true, "Does the Blacksmith refine weapons and armour?")
add_ox_quiz(1, "Czy nieudane ulepszanie u Kowala moze zniszczyc przedmiot?", true, "Can a failed refinement at the Blacksmith destroy the item?")
add_ox_quiz(1, "Czy Handlarz Bronia sprzedaje mikstury?", false, "Does the Weapon Shop Dealer sell potions?")
add_ox_quiz(1, "Czy Handlarka Roznosci sprzedaje czerwone mikstury?", true, "Does the General Store Saleswoman sell red potions?")
add_ox_quiz(1, "Czy Dozorca ulepsza bron?", false, "Does the Storekeeper refine weapons?")
add_ox_quiz(1, "Czy Stajenny sprzedaje miecze?", false, "Does the Stable Boy sell swords?")
add_ox_quiz(1, "Czy konia mozna dostac u Stajennego od 25 poziomu?", true, "Can you get a horse from the Stable Boy from level 25?")
add_ox_quiz(1, "Czy Teleporter przenosi graczy miedzy mapami?", true, "Does the Teleporter take players between maps?")
add_ox_quiz(1, "Czy Biolog Chaegirab przyjmuje badania od 30 poziomu?", true, "Does the Biologist Chaegirab take research from level 30?")
add_ox_quiz(1, "Czy Biolog Chaegirab sprzedaje konie?", false, "Does the Biologist Chaegirab sell horses?")
add_ox_quiz(1, "Czy Yonah daje szkatulke za ucho Pirata Tanaki?", true, "Does Yonah give a box for the ear of Pirate Tanaka?")

-- The events.
add_ox_quiz(1, "Czy Pirat Tanaka ucieka przed tymi, ktorzy go bija?", true, "Does Pirate Tanaka run away from those who hit him?")
add_ox_quiz(1, "Czy podczas eventu Zuo z nieba spadaja kamienie Metin?", true, "Do Metin stones fall from the sky during the Zuo event?")

-- The maps and their dungeons.
add_ox_quiz(1, "Czy Gora Sohan jest pokryta sniegiem?", true, "Is Mount Sohan covered in snow?")
add_ox_quiz(1, "Czy Pustynia Yongbi jest pokryta sniegiem?", false, "Is the Yongbi Desert covered in snow?")
add_ox_quiz(1, "Czy Ognista Ziemia to inaczej Doyyumhwaji?", true, "Is Doyyumhwaji the Fire Land?")
add_ox_quiz(1, "Czy w Dolinie Orkow mieszkaja orkowie?", true, "Do orcs live in the Orc Valley?")
add_ox_quiz(1, "Czy do Wiezy Demonow mozna wejsc majac 39 poziom?", false, "Can you enter the Demon Tower at level 39?")
add_ox_quiz(1, "Czy do Wiezy Demonow mozna wejsc od 40 poziomu?", true, "Can you enter the Demon Tower from level 40?")
add_ox_quiz(1, "Czy Wieza Demonow ma tylko jedno pietro?", false, "Does the Demon Tower have only one floor?")
add_ox_quiz(1, "Czy Azrael jest panem Katakumb Diabla?", true, "Is Azrael the master of the Devil's Catacomb?")
add_ox_quiz(1, "Czy Krolowa Pajakow mieszka w Lochu Pajakow?", true, "Does the Queen Spider live in the Spider Dungeon?")

-- The monsters and their levels (world.mob_proto).
add_ox_quiz(1, "Czy Dziki Pies ma 1 poziom?", true, "Is the Wild Dog level 1?")
add_ox_quiz(1, "Czy Wilk ma 10 poziom?", false, "Is the Wolf level 10?")
add_ox_quiz(1, "Czy Lykos ma 30 poziom?", true, "Is Lykos level 30?")
add_ox_quiz(1, "Czy Scrofa ma 30 poziom?", false, "Is Scrofa level 30?")
add_ox_quiz(1, "Czy Bera ma 30 poziom?", false, "Is Bera level 30?")
add_ox_quiz(1, "Czy Tigris ma 35 poziom?", true, "Is Tigris level 35?")
add_ox_quiz(1, "Czy Lykos to wilk?", true, "Is Lykos a wolf?")
add_ox_quiz(1, "Czy Scrofa to tygrys?", false, "Is Scrofa a tiger?")
add_ox_quiz(1, "Czy Bera to niedzwiedz?", true, "Is Bera a bear?")
add_ox_quiz(1, "Czy Tigris to niedzwiedz?", false, "Is Tigris a bear?")
add_ox_quiz(1, "Czy Wodz Orkow ma 40 poziom?", false, "Is the Chief Orc level 40?")
add_ox_quiz(1, "Czy Krolowa Pajakow ma 60 poziom?", true, "Is the Queen Spider level 60?")
add_ox_quiz(1, "Czy Dziewiec Ogonow ma 50 poziom?", false, "Is Nine Tails level 50?")
add_ox_quiz(1, "Czy Dziewiec Ogonow to lis?", true, "Is Nine Tails a fox?")
add_ox_quiz(1, "Czy Dziewiec Ogonow to smok?", false, "Is Nine Tails a dragon?")
add_ox_quiz(1, "Czy Olbrzymi Zolw ma 80 poziom?", false, "Is the Giant Tortoise level 80?")
add_ox_quiz(1, "Czy Ognisty Krol ma 90 poziom?", false, "Is the Flame King level 90?")
add_ox_quiz(1, "Czy Lodowa Wiedzma ma 55 poziom?", false, "Is the Ice Witch level 55?")
add_ox_quiz(1, "Czy Krol Demonow ma 75 poziom?", true, "Is the Demon King level 75?")
add_ox_quiz(1, "Czy Umarly Rozpruwacz ma 99 poziom?", false, "Is the Death Reaper level 99?")
add_ox_quiz(1, "Czy Azrael ma 91 poziom?", true, "Is Azrael level 91?")
add_ox_quiz(1, "Czy Azrael ma 60 poziom?", false, "Is Azrael level 60?")

-- The Metin stones.
add_ox_quiz(1, "Czy Metin Cierpienia ma 5 poziom?", true, "Is the Metin of Sorrow level 5?")
add_ox_quiz(1, "Czy Metin Walki ma 20 poziom?", false, "Is the Metin of Combat level 20?")
add_ox_quiz(1, "Czy Metin Morderstwa ma 70 poziom?", true, "Is the Metin of Murder level 70?")
add_ox_quiz(1, "Czy Metin Walki ma wyzszy poziom niz Metin Morderstwa?", false, "Is the Metin of Combat of a higher level than the Metin of Murder?")
add_ox_quiz(1, "Czy kamien Metin mozna zniszczyc bronia?", true, "Can a Metin stone be broken with a weapon?")
add_ox_quiz(1, "Czy z kamieni Metin wypadaja Ksiegi Umiejetnosci?", true, "Do skill books drop from Metin stones?")

-- The game itself.
add_ox_quiz(1, "Czy Yang to waluta w Metin2?", true, "Is Yang the currency of Metin2?")
add_ox_quiz(1, "Czy Smocze Monety kupuje sie za yang u Handlarki Roznosci?", false, "Are Dragon Coins bought for yang from the General Store Saleswoman?")
add_ox_quiz(1, "Czy w Metin2 mozna jezdzic konno?", true, "Can you ride a horse in Metin2?")
add_ox_quiz(1, "Czy w Metin2 mozna wziac slub?", true, "Can you get married in Metin2?")
add_ox_quiz(1, "Czy Metin2 powstal w Niemczech?", false, "Was Metin2 made in Germany?")

-- Poland and the world.
add_ox_quiz(1, "Czy Warszawa jest stolica Polski?", true, "Is Warsaw the capital of Poland?")
add_ox_quiz(1, "Czy Krakow jest stolica Polski?", false, "Is Krakow the capital of Poland?")
add_ox_quiz(1, "Czy Polska lezy w Azji?", false, "Is Poland in Asia?")
add_ox_quiz(1, "Czy Odra jest najdluzsza rzeka w Polsce?", false, "Is the Oder the longest river in Poland?")
add_ox_quiz(1, "Czy Wisla wpada do Morza Czarnego?", false, "Does the Vistula flow into the Black Sea?")
add_ox_quiz(1, "Czy Polska ma dostep do Morza Baltyckiego?", true, "Does Poland lie on the Baltic Sea?")
add_ox_quiz(1, "Czy Polska graniczy z Hiszpania?", false, "Does Poland border Spain?")
add_ox_quiz(1, "Czy Rysy to najwyzszy szczyt w Polsce?", true, "Is Rysy the highest peak in Poland?")
add_ox_quiz(1, "Czy Mount Everest to najwyzsza gora na Ziemi?", true, "Is Mount Everest the highest mountain on Earth?")
add_ox_quiz(1, "Czy Nil plynie przez Afryke?", true, "Does the Nile flow through Africa?")
add_ox_quiz(1, "Czy Amazonka plynie przez Europe?", false, "Does the Amazon flow through Europe?")
add_ox_quiz(1, "Czy Australia jest kontynentem?", true, "Is Australia a continent?")
add_ox_quiz(1, "Czy Grenlandia jest kontynentem?", false, "Is Greenland a continent?")
add_ox_quiz(1, "Czy Paryz jest stolica Hiszpanii?", false, "Is Paris the capital of Spain?")
add_ox_quiz(1, "Czy Berlin jest stolica Austrii?", false, "Is Berlin the capital of Austria?")
add_ox_quiz(1, "Czy Rzym jest stolica Grecji?", false, "Is Rome the capital of Greece?")
add_ox_quiz(1, "Czy Madryt jest stolica Portugalii?", false, "Is Madrid the capital of Portugal?")
add_ox_quiz(1, "Czy Tokio jest stolica Japonii?", true, "Is Tokyo the capital of Japan?")
add_ox_quiz(1, "Czy Seul jest stolica Chin?", false, "Is Seoul the capital of China?")
add_ox_quiz(1, "Czy Watykan to najmniejsze panstwo swiata?", true, "Is Vatican City the smallest country in the world?")
add_ox_quiz(1, "Czy Kanada jest wieksza od Polski?", true, "Is Canada larger than Poland?")
add_ox_quiz(1, "Czy Ocean Spokojny jest najwiekszym oceanem na Ziemi?", true, "Is the Pacific the largest ocean on Earth?")
add_ox_quiz(1, "Czy Sahara lezy w Ameryce Poludniowej?", false, "Is the Sahara in South America?")

-- Animals and plants.
add_ox_quiz(1, "Czy pajak ma osiem nog?", true, "Does a spider have eight legs?")
add_ox_quiz(1, "Czy mucha ma osiem nog?", false, "Does a fly have eight legs?")
add_ox_quiz(1, "Czy wieloryb jest ssakiem?", true, "Is a whale a mammal?")
add_ox_quiz(1, "Czy delfin jest ryba?", false, "Is a dolphin a fish?")
add_ox_quiz(1, "Czy pingwin potrafi latac?", false, "Can a penguin fly?")
add_ox_quiz(1, "Czy strus jest najwiekszym zyjacym ptakiem?", true, "Is the ostrich the largest living bird?")
add_ox_quiz(1, "Czy nietoperz jest ptakiem?", false, "Is a bat a bird?")
add_ox_quiz(1, "Czy krokodyl jest gadem?", true, "Is a crocodile a reptile?")
add_ox_quiz(1, "Czy zaba jest gadem?", false, "Is a frog a reptile?")
add_ox_quiz(1, "Czy zyrafa jest najwiekszym zwierzeciem zyjacym na ladzie?", false, "Is the giraffe the largest animal living on land?")
add_ox_quiz(1, "Czy gepard jest najszybszym zwierzeciem ladowym?", true, "Is the cheetah the fastest land animal?")
add_ox_quiz(1, "Czy kot jest gadem?", false, "Is a cat a reptile?")
add_ox_quiz(1, "Czy pszczoly wytwarzaja miod?", true, "Do bees make honey?")
add_ox_quiz(1, "Czy rosliny wytwarzaja tlen?", true, "Do plants produce oxygen?")
add_ox_quiz(1, "Czy grzyby sa roslinami?", false, "Are mushrooms plants?")
add_ox_quiz(1, "Czy pomidor jest w botanice owocem?", true, "Is a tomato a fruit in botany?")

-- The sky and the world around us.
add_ox_quiz(1, "Czy Ziemia krazy wokol Slonca?", true, "Does the Earth orbit the Sun?")
add_ox_quiz(1, "Czy Ziemia jest plaska?", false, "Is the Earth flat?")
add_ox_quiz(1, "Czy Slonce jest planeta?", false, "Is the Sun a planet?")
add_ox_quiz(1, "Czy Ksiezyc jest gwiazda?", false, "Is the Moon a star?")
add_ox_quiz(1, "Czy Mars jest nazywany Czerwona Planeta?", true, "Is Mars called the Red Planet?")
add_ox_quiz(1, "Czy Jowisz jest najwieksza planeta Ukladu Slonecznego?", true, "Is Jupiter the largest planet of the Solar System?")
add_ox_quiz(1, "Czy Neptun jest planeta najblizej Slonca?", false, "Is Neptune the planet closest to the Sun?")
add_ox_quiz(1, "Czy Wenus ma ksiezyc?", false, "Does Venus have a moon?")
add_ox_quiz(1, "Czy woda wrze w 100 stopniach Celsjusza przy normalnym cisnieniu?", true, "Does water boil at 100 degrees Celsius at normal pressure?")
add_ox_quiz(1, "Czy woda zamarza w 10 stopniach Celsjusza?", false, "Does water freeze at 10 degrees Celsius?")
add_ox_quiz(1, "Czy lod plywa po wodzie?", true, "Does ice float on water?")
add_ox_quiz(1, "Czy dzwiek rozchodzi sie w prozni?", false, "Does sound travel through a vacuum?")
add_ox_quiz(1, "Czy swiatlo jest szybsze od dzwieku?", true, "Is light faster than sound?")
add_ox_quiz(1, "Czy magnes przyciaga zloto?", false, "Does a magnet attract gold?")
add_ox_quiz(1, "Czy zloto rdzewieje?", false, "Does gold rust?")
add_ox_quiz(1, "Czy diament jest zbudowany z wegla?", true, "Is a diamond made of carbon?")
add_ox_quiz(1, "Czy kilogram pierza wazy mniej niz kilogram zelaza?", false, "Does a kilogram of feathers weigh less than a kilogram of iron?")
add_ox_quiz(1, "Czy z niebieskiego i zoltego powstaje kolor zielony?", true, "Do blue and yellow make green?")
add_ox_quiz(1, "Czy z czerwonego i zoltego powstaje kolor fioletowy?", false, "Do red and yellow make purple?")
add_ox_quiz(1, "Czy tecza ma siedem kolorow?", true, "Does a rainbow have seven colours?")
add_ox_quiz(1, "Czy dorosly czlowiek ma 206 kosci?", true, "Does an adult human have 206 bones?")
add_ox_quiz(1, "Czy czlowiek ma trzy pluca?", false, "Does a human have three lungs?")

-- Numbers and time.
add_ox_quiz(1, "Czy 7 razy 8 to 56?", true, "Is 7 times 8 equal to 56?")
add_ox_quiz(1, "Czy 9 razy 9 to 72?", false, "Is 9 times 9 equal to 72?")
add_ox_quiz(1, "Czy 100 podzielone przez 4 to 20?", false, "Is 100 divided by 4 equal to 20?")
add_ox_quiz(1, "Czy 15 plus 27 to 52?", false, "Is 15 plus 27 equal to 52?")
add_ox_quiz(1, "Czy 7 jest liczba pierwsza?", true, "Is 7 a prime number?")
add_ox_quiz(1, "Czy 21 jest liczba pierwsza?", false, "Is 21 a prime number?")
add_ox_quiz(1, "Czy suma katow w trojkacie wynosi 180 stopni?", true, "Do the angles of a triangle add up to 180 degrees?")
add_ox_quiz(1, "Czy kwadrat ma piec bokow?", false, "Does a square have five sides?")
add_ox_quiz(1, "Czy tydzien ma osiem dni?", false, "Does a week have eight days?")
add_ox_quiz(1, "Czy rok przestepny ma 366 dni?", true, "Does a leap year have 366 days?")
add_ox_quiz(1, "Czy luty ma zawsze 30 dni?", false, "Does February always have 30 days?")
add_ox_quiz(1, "Czy doba ma 24 godziny?", true, "Does a day have 24 hours?")
add_ox_quiz(1, "Czy godzina ma 100 minut?", false, "Does an hour have 100 minutes?")

-- People, books and games.
add_ox_quiz(1, "Czy Fryderyk Chopin byl malarzem?", false, "Was Frederic Chopin a painter?")
add_ox_quiz(1, "Czy Maria Sklodowska-Curie otrzymala dwie Nagrody Nobla?", true, "Did Marie Sklodowska-Curie win two Nobel Prizes?")
add_ox_quiz(1, "Czy Mikolaj Kopernik twierdzil, ze Slonce krazy wokol Ziemi?", false, "Did Nicolaus Copernicus claim that the Sun orbits the Earth?")
add_ox_quiz(1, "Czy Adam Mickiewicz napisal Pana Tadeusza?", true, "Did Adam Mickiewicz write Pan Tadeusz?")
add_ox_quiz(1, "Czy Henryk Sienkiewicz napisal Pana Tadeusza?", false, "Did Henryk Sienkiewicz write Pan Tadeusz?")
add_ox_quiz(1, "Czy w pilce noznej druzyna ma na boisku 9 zawodnikow?", false, "Does a football team have 9 players on the pitch?")
add_ox_quiz(1, "Czy w szachach goniec porusza sie po skosie?", true, "In chess, does the bishop move diagonally?")
add_ox_quiz(1, "Czy w szachach wieza porusza sie po skosie?", false, "In chess, does the rook move diagonally?")
add_ox_quiz(1, "Czy letnie igrzyska olimpijskie odbywaja sie co cztery lata?", true, "Are the Summer Olympic Games held every four years?")
