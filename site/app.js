(function () {
  "use strict";

  var state = { manufacturers: [], byId: {}, selectedId: null };

  var listEl = document.getElementById("manufacturer-list");
  var searchEl = document.getElementById("search");
  var emptyEl = document.getElementById("empty-state");
  var detailEl = document.getElementById("detail");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function confidenceClass(level) {
    if (level === "confirmed") return "confirmed";
    if (level === "unresearched") return "unresearched";
    return "needs_review";
  }

  function confidenceLabel(level) {
    if (level === "confirmed") return "Megerősítve";
    if (level === "unresearched") return "Még nincs kikutatva";
    return "Ellenőrzésre vár";
  }

  function yearRange(startYear, endYear) {
    var start = startYear == null ? "?" : startYear;
    var end = endYear == null ? "present" : endYear;
    return start + " – " + end;
  }

  function renderList(filterText) {
    var q = (filterText || "").trim().toLowerCase();
    var items = state.manufacturers.filter(function (m) {
      return !q || m.canonical_name.toLowerCase().indexOf(q) !== -1;
    });

    listEl.innerHTML = "";
    if (!items.length) {
      var none = document.createElement("li");
      none.className = "no-results";
      none.textContent = "Nincs egyező gyártó.";
      listEl.appendChild(none);
      return;
    }

    items.forEach(function (m) {
      var li = document.createElement("li");
      li.dataset.id = m.id;
      if (m.id === state.selectedId) li.classList.add("selected");

      var badge = document.createElement("span");
      badge.className = "badge " + confidenceClass(m.confidence_level);

      var label = document.createElement("span");
      label.textContent = m.canonical_name;
      label.style.flex = "1";

      li.appendChild(label);
      li.appendChild(badge);
      li.addEventListener("click", function () { selectManufacturer(m.id); });
      listEl.appendChild(li);
    });
  }

  function renderDetail(m) {
    if (!m) {
      emptyEl.hidden = false;
      detailEl.hidden = true;
      detailEl.innerHTML = "";
      return;
    }
    emptyEl.hidden = true;
    detailEl.hidden = false;

    var isConfirmed = m.confidence_level === "confirmed";
    var isUnresearched = m.confidence_level === "unresearched";
    var html = "";

    html += "<h1>" + escapeHtml(m.canonical_name) + "</h1>";
    html += '<div class="meta-row">';
    html += '<span class="status-pill ' + confidenceClass(m.confidence_level) + '">' +
      confidenceLabel(m.confidence_level) + "</span>";
    var place = [m.city, m.country].filter(Boolean).join(", ");
    if (place) html += "<span>" + escapeHtml(place) + "</span>";
    // A single "1969-2010" reads better than two separate year chips, and an
    // open-ended range still says something: the company is still going.
    if (m.founded_year || m.ended_year) {
      html += "<span>" + escapeHtml(String(m.founded_year || "?")) +
        (m.ended_year ? "\u2013" + escapeHtml(String(m.ended_year)) : "\u2013") + "</span>";
    }
    if (m.status) html += "<span>" + escapeHtml(m.status) + "</span>";
    html += "</div>";

    if (m.founders) {
      html += '<p class="founders">Alapítók: ' + escapeHtml(m.founders) + "</p>";
    }

    if (isUnresearched) {
      html += '<div class="unresearched-notice">Ez a gyártó egyelőre csak egy másik cég kutatása során ' +
        "került elő kapcsolódó névként, önmagában még nem lett kikutatva. Az alábbi adatok hiányoznak, amíg ez meg nem történik.</div>";
    } else if (!isConfirmed) {
      html += '<div class="review-notice">Ez a bejegyzés még nincs függetlenül megerősítve. ' +
        "Az alábbi adatok hiányosak, ellenőrizetlenek, vagy egyetlen, nem megerősített forrásból származhatnak.</div>";
    }

    if (m.short_history) {
      html += "<section><h2>Történet</h2><p>" + escapeHtml(m.short_history) + "</p>";
      if (m.long_history) {
        html += '<button type="button" class="expand-toggle" id="long-history-toggle">Bővebben</button>' +
          '<p class="long-history" id="long-history-text" hidden>' + escapeHtml(m.long_history) + "</p>";
      }
      html += "</section>";
    }

    if (m.official_website) {
      html += "<section><h2>Hivatalos weboldal</h2><p><a href=\"" + escapeHtml(m.official_website) +
        "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(m.official_website) + "</a></p></section>";
    }

    if (m.instruments && m.instruments.length) {
      html += '<section><h2>Hangszerek <span class="count">' + m.instruments.length +
        "</span></h2><ul class=\"instrument-list\">";
      m.instruments.forEach(function (it) {
        html += "<li>" + escapeHtml(it.name) +
          (it.year ? ' <span class="year">' + escapeHtml(String(it.year)) + "</span>" : "") +
          "</li>";
      });
      html += "</ul></section>";
    }

    if (m.name_history && m.name_history.length) {
      html += "<section><h2>Névtörténet</h2><ul class=\"timeline\">";
      m.name_history.forEach(function (nh) {
        html += "<li><strong>" + escapeHtml(nh.name) + "</strong> — " +
          escapeHtml(yearRange(nh.start_year, nh.end_year)) + "</li>";
      });
      html += "</ul></section>";
    }

    if (m.relations && m.relations.length) {
      html += "<section><h2>Kapcsolódó gyártók</h2><ul class=\"relations-list\">";
      m.relations.forEach(function (rel) {
        var relType = (rel.relation_type || "").replace(/_/g, " ");
        html += "<li><span class=\"rel-type\">" + escapeHtml(relType) + "</span> — " +
          escapeHtml(rel.related_name || "ismeretlen") +
          (rel.year ? " (" + escapeHtml(rel.year) + ")" : "") + "</li>";
      });
      html += "</ul></section>";
    }

    detailEl.innerHTML = html;

    var toggle = document.getElementById("long-history-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var text = document.getElementById("long-history-text");
        var expanded = !text.hidden;
        text.hidden = expanded;
        toggle.textContent = expanded ? "Bővebben" : "Kevesebbet";
      });
    }
  }

  function selectManufacturer(id) {
    state.selectedId = id;
    renderList(searchEl.value);
    renderDetail(state.byId[id]);
  }

  function init(manufacturers) {
    state.manufacturers = manufacturers;
    state.byId = {};
    manufacturers.forEach(function (m) { state.byId[m.id] = m; });
    renderList("");
    renderDetail(null);

    searchEl.addEventListener("input", function () {
      renderList(searchEl.value);
    });
  }

  fetch("data/manufacturers.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) {
      emptyEl.innerHTML = "<h1>Synthsworld</h1><p>Could not load manufacturer data.</p>";
      console.error(err);
    });
})();
