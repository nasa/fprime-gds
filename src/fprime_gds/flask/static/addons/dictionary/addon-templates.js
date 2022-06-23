export let dictionary_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-repeater">
        <ul class="nav nav-tabs">
          <li :class="['nav-item', 'nav-link', { active: active == key }]"
              v-for="key in Object.keys(this.dictionaries)" >
              <a @click="change(key)">{{ capitalize(key)  }}</a>
          </li>
        </ul>
        <div class="container-fluid fp-flex-repeater" v-show="active == key" v-for="key in Object.keys(this.dictionaries)">
            <h2>{{ capitalize(key) }} Dictionary</h2>
            <fp-table :header-columns="['ID', 'Name', 'Description']"
                :items="dictionaries[key]"
                :item-to-columns="columnify"
                :item-to-unique="(item) => item"
            ></fp-table>
        </div>
    </div>
</div>
`;
export let version_template = `
<small>
Dictionary Version: {{ project_version }}
Dictionary Schema: {{ framework_version }}
</small>
`;
