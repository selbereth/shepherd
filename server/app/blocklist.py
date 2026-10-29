"""Built-in list of well-known adult/gambling domains, seeded into the ban list.

Seeded once per BLOCKLIST_VERSION: sites you unban stay unbanned until the
version is bumped. Subdomains are covered by the ban-list matching.
"""
BLOCKLIST_VERSION = 1

ADULT = """
pornhub.com xvideos.com xnxx.com xhamster.com redtube.com youporn.com spankbang.com
tube8.com tnaflix.com porn.com pornone.com eporner.com beeg.com txxx.com hclips.com
brazzers.com realitykings.com bangbros.com naughtyamerica.com mofos.com
chaturbate.com stripchat.com livejasmin.com bongacams.com cam4.com myfreecams.com camsoda.com
onlyfans.com fansly.com manyvids.com clips4sale.com
rule34.xxx e-hentai.org nhentai.net hentaihaven.xxx hanime.tv gelbooru.com e621.net
motherless.com fapello.com thothub.to erome.com sex.com xtube.com
""".split()

GAMBLING = """
bet365.com draftkings.com fanduel.com bovada.lv betway.com 888casino.com stake.com
pokerstars.com williamhill.com ladbrokes.com betmgm.com caesars.com/sportsbook
""".split()

DOMAINS = sorted({d for d in ADULT + GAMBLING if "/" not in d})
